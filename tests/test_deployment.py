"""S1: isolated runtime, real process ownership/recovery and full instance backup."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _env(runtime):
    env = dict(os.environ)
    for key in list(env):
        if key.endswith(("_API_KEY", "_SEARCH_KEY")) or key in ("APP_ACCESS_TOKEN", "WRA_DATA_DIR"):
            env[key] = ""
    env.update(WENSHU_RUNTIME_DIR=str(runtime), WENSHU_DATA_DIR=str(runtime / "resource"),
               WENSHU_LOG_DIR=str(runtime / "log"), WENSHU_MIN_FREE_MB="1")
    return env


def _run(runtime, code, **kwargs):
    return subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT,
                          env=_env(runtime), capture_output=True, text=True, encoding="utf-8", timeout=45, **kwargs)


def test_cli_background_output_is_utf8_even_with_ascii_process_pipes(tmp_path):
    env = _env(tmp_path / "runtime")
    env.update(PYTHONIOENCODING="ascii", PYTHONUTF8="0")
    result = subprocess.run([sys.executable, "-X", "utf8=0", "-m", "app", "--version"],
                            cwd=ROOT, env=env, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert "文枢" in result.stdout.decode("utf-8")


def test_runtime_upgrade_preserves_config_and_uses_current_frontend(tmp_path):
    runtime = tmp_path / "持久目录"
    init = _run(runtime, "from app.core import config; from app.storage import db; db.init_db(); print(config.RUNTIME_ROOT)", check=True)
    assert str(runtime) in init.stdout
    settings = runtime / "config" / "settings.yaml"
    settings.write_text("create:\n  target_word_count: 1234\n", encoding="utf-8")
    prompt = runtime / "config" / "prompts" / "creator" / "draft.j2"
    prompt.write_text("user prompt", encoding="utf-8")
    (runtime / ".env").write_text("APP_ACCESS_TOKEN=preserved-secret\n", encoding="utf-8")
    # A stale frontend under the persistent directory must not hide new program assets.
    (runtime / "web" / "dist").mkdir(parents=True)
    (runtime / "web" / "dist" / "index.html").write_text("old UI", encoding="utf-8")
    config_before = settings.read_bytes(), prompt.read_bytes(), (runtime / ".env").read_bytes()
    result = _run(runtime, """
from app.core import config
from app.main import WEB_DIST
assert config.get('create.target_word_count') == 1234
assert WEB_DIST == config.BUNDLE_ROOT / 'web' / 'dist'
config.ensure_runtime_assets()
assert config.data_dir() == config.RUNTIME_ROOT / 'resource'
""", check=True)
    assert config_before == (settings.read_bytes(), prompt.read_bytes(), (runtime / ".env").read_bytes())
    assert result.returncode == 0


def test_ready_rejects_full_disk_and_unwritable_storage(app_client, monkeypatch):
    from app.services import readiness
    real_usage = readiness.shutil.disk_usage
    usage_type = type(real_usage(ROOT))
    monkeypatch.setattr(readiness.shutil, "disk_usage", lambda p: usage_type(100, 100, 0))
    assert app_client.get("/api/health").status_code == 200
    assert app_client.get("/api/ready").status_code == 503
    monkeypatch.setattr(readiness.shutil, "disk_usage", real_usage)

    def denied(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(readiness.tempfile, "TemporaryFile", denied)
    assert app_client.get("/api/ready").status_code == 503


@pytest.mark.parametrize("invalid", ["../escaped", "C:/outside", ".", ""])
def test_restore_rejects_manifest_paths_before_creating_destination(tmp_path, invalid):
    from app.services.instance_backup import restore_instance
    source, destination = tmp_path / "backup", tmp_path / "restored"
    source.mkdir()
    manifest = {"format": 1, "files": {invalid: "bad", "resource/app.db": "bad", "config/settings.yaml": "bad"}}
    (source / "backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="路径"):
        restore_instance(source, destination)
    assert not destination.exists()


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start(runtime, port, log, slow_ingest=False):
    args = [sys.executable, "-X", "utf8", "-m", "app", "--runtime-dir", str(runtime),
            "--data-dir", str(runtime / "resource"), "--log-dir", str(runtime / "log"),
            "--port", str(port), "--no-browser"]
    if slow_ingest:
        code = """
import sys, time
from app.pipeline import queue
original = queue.register_defaults
def register(llm=None):
    original(llm)
    queue._handlers['ingest'] = lambda aid, payload: time.sleep(120)
queue.register_defaults = register
sys.argv = ['wenshu'] + sys.argv[1:]
from app.__main__ import main
main()
"""
        args = [sys.executable, "-X", "utf8", "-c", code] + args[5:]
    return subprocess.Popen(args, cwd=ROOT, env=_env(runtime), stdout=log, stderr=log)


def _wait(client, process, path="/api/ready", predicate=lambda r: r.status_code == 200):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"service exited: {process.returncode}")
        try:
            response = client.get(path)
            if predicate(response):
                return response
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise AssertionError(f"timeout: {path}")


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_cli_process_restart_full_flow_and_verified_backup(tmp_path):
    runtime, backup, restored = (tmp_path / name for name in ("instance", "backup", "restored"))
    port = _port()
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log, httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
        process = _start(runtime, port, log)
        try:
            _wait(client, process)
            # Backups must be refused while the process holds the data-root lock.
            blocked = subprocess.run([sys.executable, "-X", "utf8", "-m", "app", "--backup", str(backup)],
                cwd=ROOT, env=_env(runtime), capture_output=True, timeout=15)
            assert blocked.returncode != 0 and not backup.exists()
            duplicate = _start(runtime, _port(), log)
            try:
                assert duplicate.wait(timeout=15) != 0
            finally:
                _stop(duplicate)
            aid = client.post("/api/articles", json={"title": "S1隔离验证", "auto_collect": False}).json()["article"]["id"]
            source = "本地资料收集：团队将资料整理为文稿，审核后导出发布包。持久配置与素材独立保存。"
            uploaded = client.post(f"/api/articles/{aid}/materials/upload-batch",
                files=[("files", ("source.md", source.encode(), "text/markdown"))])
            assert uploaded.status_code == 200 and not uploaded.json()["failed"]
            assert client.get(f"/api/articles/{aid}").json()["status"] == "COLLECTED"
            for stage in ("create", "review"):
                assert client.post(f"/api/articles/{aid}/advance", json={"stage": stage}).status_code == 200
                _wait(client, process, f"/api/jobs?article_id={aid}", lambda r: bool(r.json()["jobs"]) and
                      all(j["status"] == "done" for j in r.json()["jobs"]))
            draft = client.get(f"/api/articles/{aid}/draft").json()["draft"]
            paragraph = next(b for b in draft["doc"]["blocks"] if b["type"] == "paragraph")
            edited = client.put(f"/api/drafts/{draft['id']}/edit", json={
                "expected_revision": draft["doc"]["edit_revision"],
                "ops": [{"op": "update", "block_id": paragraph["id"], "text": "人工编辑后内容保留，重启与恢复均能读取。"}]})
            assert edited.status_code == 200, edited.text
            _wait(client, process, f"/api/jobs?article_id={aid}", lambda r: all(j["status"] == "done" for j in r.json()["jobs"]))
            draft = client.get(f"/api/articles/{aid}/draft").json()["draft"]
            finalized = client.post(f"/api/articles/{aid}/finalize", json={"force": True,
                "expected_version": draft["version"], "expected_revision": draft["doc"]["edit_revision"]})
            assert finalized.status_code == 200, finalized.text
            assert client.post(f"/api/articles/{aid}/publish", json={"platforms": ["wechat_mp", "xhs", "weibo", "x"]}).status_code == 200
            _wait(client, process, f"/api/jobs?article_id={aid}", lambda r: all(j["status"] == "done" for j in r.json()["jobs"]))
            before = client.get(f"/api/articles/{aid}").json()
            draft_before = client.get(f"/api/articles/{aid}/draft").json()
            exports = client.get(f"/api/articles/{aid}/exports").json()["files"]
            assert any("/xhs/" in p and p.endswith(".png") for p in exports)
            assert {j["platform"] for j in before["publish_jobs"]} == {"wechat_mp", "xhs", "weibo", "x"}
            for path in exports:
                assert client.get("/files/" + path).status_code == 200
            _stop(process)
            process = _start(runtime, port, log)
            _wait(client, process)
            assert client.get(f"/api/articles/{aid}/draft").json() == draft_before
            after = client.get(f"/api/articles/{aid}").json()
            for key in ("materials_count", "versions", "latest_review", "publish_jobs", "status"):
                assert before[key] == after[key]
        finally:
            _stop(process)
    command = [sys.executable, "-X", "utf8", "-m", "app"]
    subprocess.run(command + ["--backup", str(backup)], cwd=ROOT, env=_env(runtime), capture_output=True, check=True, timeout=30)
    subprocess.run(command + ["--runtime-dir", str(restored), "--restore", str(backup)], cwd=ROOT, env=_env(runtime), capture_output=True, check=True, timeout=30)
    with sqlite3.connect(restored / "resource" / "app.db") as conn:
        assert conn.execute("SELECT status FROM articles WHERE id=?", (aid,)).fetchone()[0] == "DONE"
    # Isolated restore keeps old config verbatim; explicit CLI paths prevent opening its original root.
    with (tmp_path / "restore.log").open("w", encoding="utf-8") as log, httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
        process = _start(restored, port, log)
        try:
            _wait(client, process)
            assert client.get(f"/api/articles/{aid}/draft").json() == draft_before
            assert client.get(f"/api/articles/{aid}/exports").json()["files"] == exports
        finally:
            _stop(process)
    from app.services.instance_backup import restore_instance
    with pytest.raises(ValueError, match="全新"):
        restore_instance(backup, restored)
    material_file = next(p for p in (backup / "resource").rglob("*.md"))
    material_file.write_text("tampered", encoding="utf-8")
    rejected = tmp_path / "rejected"
    with pytest.raises(ValueError, match="SHA256"):
        restore_instance(backup, rejected)
    assert not rejected.exists()


def test_worker_recovers_claimed_job_after_process_kill(tmp_path):
    runtime = tmp_path / "recover"
    seeded = _run(runtime, """
from app.storage import db, dao
db.init_db()
print(dao.enqueue_job('ingest', None, {'urls': []}))
""", check=True)
    jid = seeded.stdout.strip()
    with (tmp_path / "recovery.log").open("w", encoding="utf-8") as log:
        process = _start(runtime, _port(), log, slow_ingest=True)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with sqlite3.connect(runtime / "resource" / "app.db") as conn:
                    state = conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
                if state == "running":
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("job was not claimed")
            process.kill()
            process.wait(timeout=10)
            port = _port()
            process = _start(runtime, port, log)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                _wait(client, process)
                result = _wait(client, process, "/api/jobs", lambda r: r.json()["jobs"][0]["status"] == "done")
                job = result.json()["jobs"][0]
                assert job["id"] == jid and job["attempts"] == 2
        finally:
            _stop(process)
