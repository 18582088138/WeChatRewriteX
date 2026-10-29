"""Windows exe acceptance with disposable data and no real model/search credentials.

Usage: python scripts/frozen_smoke.py <release-package-directory>
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import sys

import httpx


def main():
    package = Path(sys.argv[1]).resolve()
    executable = package / "文枢.exe"
    assert executable.is_file()
    with tempfile.TemporaryDirectory(prefix="wenshu-frozen-") as temp:
        root = Path(temp)
        copied = root / executable.name
        if (package / "_internal").is_dir():
            shutil.copytree(package / "_internal", root / "_internal")
        shutil.copy2(executable, copied)
        env = {**os.environ, "WENSHU_DATA_DIR": str(root / "data"),
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               "WENSHU_LOG_DIR": str(root / "logs"),
               "PLAYWRIGHT_BROWSERS_PATH": str(package / "playwright-browsers")}
        for key in ("DEEPSEEK_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                    "TAVILY_API_KEY", "BING_SEARCH_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY",
                    "COVERR_API_KEY", "MINIMAX_API_KEY", "MINIMAX_TTS_API_KEY", "APP_ACCESS_TOKEN"):
            env[key] = ""
        version = subprocess.check_output([str(copied), "--version"], env=env, timeout=30).decode("utf-8")
        info = json.loads(subprocess.check_output([str(copied), "--build-info"], env=env, timeout=30))
        assert info["version"] in version
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with (root / "server.log").open("wb") as output:
            process = subprocess.Popen([str(copied), "--no-browser", "--port", str(port)],
                                       cwd=root, env=env, stdout=output, stderr=output)
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=40) as client:
                    def wait(check, seconds=60):
                        deadline = time.monotonic() + seconds
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise AssertionError("exe exited: " + (root / "server.log").read_text(encoding="utf-8", errors="replace")[-3000:])
                            try:
                                if check():
                                    return
                            except (httpx.HTTPError, KeyError):
                                pass
                            time.sleep(0.2)
                        raise AssertionError("exe acceptance timed out")
                    def request(method, url, **kwargs):
                        response = client.request(method, url, **kwargs)
                        response.raise_for_status()
                        return response.json()
                    wait(lambda: client.get("/api/ready").status_code == 200)
                    assert client.get("/").status_code == 200
                    env_file = root / ".env"
                    for key in ("frozen-test-first", "frozen-test-second"):
                        env_file.write_text(f"DEEPSEEK_API_KEY={key}\n", encoding="utf-8")
                        reloaded = request("POST", "/api/settings/reload-env")
                        assert reloaded["services"]["llm_purposes"]["create"]
                        assert key not in json.dumps(reloaded)
                    env_file.write_text("", encoding="utf-8")
                    assert not request("POST", "/api/settings/reload-env")["services"]["llm_available"]
                    aid = request("POST", "/api/articles", json={"title": "冻结包验收", "auto_collect": False})["article"]["id"]
                    base = f"/api/articles/{aid}"
                    request("POST", base + "/materials/upload-batch", files={"files": ("source.md", "冻结程序需要验证实际文稿生成、编辑、审稿和四平台导出。".encode(), "text/markdown")})
                    request("POST", base + "/advance", json={"stage": "create"})
                    wait(lambda: request("GET", base)["status"] == "DRAFTED")
                    draft = request("GET", base + "/draft")["draft"]
                    block = next(b for b in draft["doc"]["blocks"] if b["type"] == "paragraph")
                    edited = request("PUT", f"/api/drafts/{draft['id']}/edit", json={
                        "expected_revision": draft["doc"]["edit_revision"],
                        "ops": [{"op": "update", "block_id": block["id"], "text": "冻结程序的人工修订内容。"}]})
                    assert edited["version"] == 1
                    wait(lambda: request("GET", base)["status"] in ("DRAFTED", "EDITING"))
                    request("POST", base + "/finalize", json={"force": True})
                    request("POST", base + "/publish", json={"platforms": ["wechat_mp", "weibo", "x", "xhs"]})
                    wait(lambda: request("GET", base)["status"] == "DONE")
                    files = request("GET", base + "/exports")["files"]
                    for suffix in ("article.html", "weibo.txt", "thread.json", "page-01.png"):
                        path = next(p for p in files if p.endswith(suffix))
                        assert client.get("/files/" + path).status_code == 200
                    assert not any("/runs/" in p or p.endswith("snapshot.json") for p in files)
                    assert client.get("/files/app.db").status_code == 404
                    head = request("GET", base + "/draft")["draft"]
                    edited = request("PUT", f"/api/drafts/{head['id']}/edit", json={
                        "expected_revision": head["doc"]["edit_revision"],
                        "ops": [{"op": "update", "block_id": block["id"], "text": "冻结包定稿后进入新版本。"}]})
                    assert edited["version"] == 2
                    historical = request("GET", base + "/draft?version=1")["draft"]
                    assert historical["status"] == "finalized"
                    print(f"Frozen {info['version']} smoke passed: environment reload, frontend, working versions, finalization, all 4 exports, cards and downloads")
            finally:
                if process.poll() is None:
                    # PyInstaller has a bootloader child: terminate only this owned process tree.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
