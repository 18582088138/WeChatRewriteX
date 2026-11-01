import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from scripts import nuc_http_probe as probe


@pytest.mark.parametrize("url", ["http://192.168.1.8:8000", "https://user:password@example.com", "https://example.com?token=secret", "https://example.com/api"])
def test_origin_validation_rejects_plain_remote_credentials_and_paths(url):
    with pytest.raises(ValueError):
        probe.validate_url(url)


def test_authorized_reads_use_session_and_never_write_private_content():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"csrf": "csrf-secret"}, headers={"set-cookie": "wenshu_member=session-secret; Path=/; HttpOnly"})
        assert "session-secret" in request.headers.get("cookie", "")
        if request.url.path == "/api/auth/logout":
            assert request.headers["X-Wenshu-CSRF"] == "csrf-secret"
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/articles":
            return httpx.Response(200, json={"articles": [{"id": "private-project", "title": "private-title"}]})
        return httpx.Response(200, json={"id": "private-project", "title": "private-title"})
    with httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler)) as client:
        result = probe.probe(client, "private-login", "private-password", "member-1", .02, 0, 5)
    text = json.dumps(result)
    for sensitive in ("private-project", "private-title", "private-login", "private-password", "session-secret", "csrf-secret"):
        assert sensitive not in text
    assert probe.summarize([result])["successful_reads"] > 0
    assert result["logout_status"] == 200
    assert {path for method, path in calls if method == "POST"} == {"/api/auth/login", "/api/auth/logout"}


def test_failed_login_is_setup_failure_not_successful_read():
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(lambda r: httpx.Response(401))) as client:
        result = probe.probe(client, "user", "wrong", "member-1", .01, 0, 1)
    summary = probe.summarize([result])
    assert summary["failed_reads_or_setup"] == 1
    assert not summary["all_members_authenticated"] and summary["p95_ms"] is None


def test_http_failures_are_counted_and_body_not_exported():
    listing = 0
    def handler(request):
        nonlocal listing
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"csrf": "csrf"})
        if request.url.path == "/api/auth/logout":
            return httpx.Response(200)
        listing += 1
        if listing == 1:
            return httpx.Response(200, json={"articles": []})
        return httpx.Response(503, text="private error text")
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        result = probe.probe(client, "user", "password", "member-1", .02, 0, 1)
    assert probe.summarize([result])["failed_reads_or_setup"] > 0
    assert "private error text" not in json.dumps(result)


def test_percentiles_and_supported_origins():
    assert probe.percentile([20, 100, 40], .95) == 100
    assert probe.percentile([20, 100, 40], .5) == 40
    assert probe.validate_url("http://localhost:8000/") == "http://localhost:8000"
    assert probe.validate_url("https://example.com") == "https://example.com"


def test_logout_failure_is_reported_even_after_successful_reads():
    result = {"authenticated": True, "samples": [{"status": 200, "milliseconds": 1}],
              "failures": [], "logout_status": 503}
    assert probe.summarize([result])["failed_reads_or_setup"] == 1


def test_three_separate_sessions_against_real_loopback_server(tmp_path):
    env = dict(os.environ)
    env.update(WENSHU_RUNTIME_DIR=str(tmp_path), WENSHU_DATA_DIR=str(tmp_path / "resource"),
               WENSHU_LOG_DIR=str(tmp_path / "log"), WENSHU_TEAM_MODE="1", APP_ACCESS_TOKEN="")
    for key in list(env):
        if key.endswith(("_API_KEY", "_SEARCH_KEY")):
            env[key] = ""
    code = """
import socket,threading,time,httpx,uvicorn
from concurrent.futures import ThreadPoolExecutor
from app.main import create_app
from app.services import team
from app.storage import db
from scripts.nuc_http_probe import probe,summarize
app=create_app(start_worker=False)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));sock.listen(128)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        assert server.started
        team.initialize_admin('admin','Admin','fixture-password')
        team.create_member('writer','Writer','fixture-password')
        team.create_member('maintainer','Maintainer','fixture-password','maintainer')
        names=['admin','writer','maintainer']
        def run(i):
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False) as client:
                return probe(client,names[i],'fixture-password',f'member-{i+1}',.2,.01,5)
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,range(3)))
        summary=summarize(results)
        assert summary['all_members_authenticated'] and summary['successful_reads']>0 and summary['failed_reads_or_setup']==0,summary
        assert all(r['logout_status']==200 for r in results)
        assert db.query_one('SELECT count(*) AS n FROM member_sessions')['n']==0
    finally:
        server.should_exit=True;thread.join(timeout=10)
        assert not thread.is_alive()
"""
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
