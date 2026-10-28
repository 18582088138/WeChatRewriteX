from pathlib import Path
from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import create_app
from app.services import http, network_policy
from app.services.crawl import registry
from app.services.crawl.base import CrawlError
from app.storage import dao, db, library


def test_factory_does_not_recover_live_job():
    jid = dao.enqueue_job("unknown", None, {"unique": "factory"})
    db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    app = create_app()
    assert not app.state.ready
    assert db.query_one("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "running"
    db.execute("DELETE FROM jobs WHERE id=?", (jid,))


def test_runtime_lock_excludes_second_owner(tmp_path):
    from app.pipeline.runtime_lock import RuntimeLock
    first = RuntimeLock(tmp_path).acquire()
    try:
        with pytest.raises(RuntimeError, match="已有运行实例"):
            RuntimeLock(tmp_path).acquire()
    finally:
        first.close()
    RuntimeLock(tmp_path).acquire().close()


def test_token_cookie_files_and_internal_boundary(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "test-access-token")
    mid, _ = library.ingest_bytes(b"image", "image.png", "common")
    with TestClient(create_app(start_worker=False)) as client:
        assert client.get("/api/articles").status_code == 401
        assert client.get("/api/articles?token=test-access-token").status_code == 401
        auth = {"Authorization": "Bearer test-access-token"}
        result = client.get("/api/session", headers=auth)
        assert result.status_code == 200 and "httponly" in result.headers["set-cookie"].lower()
        assert "test-access-token" not in result.headers["set-cookie"]
        assert client.get("/api/articles").status_code == 200
        assert client.get("/api/ready").status_code == 200
        assert client.get("/files/app.db").status_code == 404
        assert client.get("/files/.worker.lock").status_code == 404
        assert client.get("/files/" + dao.get_material(mid)["path"]).status_code == 200


def test_unsafe_fixture_disabled_in_production():
    before = registry._CRAWLERS[:]
    registry._CRAWLERS[:] = [c for c in before if not isinstance(c, registry.FixtureCrawler)]
    try:
        with pytest.raises(CrawlError):
            registry.fetch("fixture://sample_article.md")
    finally:
        registry._CRAWLERS[:] = before
    with pytest.raises(CrawlError):
        registry.FixtureCrawler().fetch("fixture://../../.env")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/", "http://[::1]/",
    "http://169.254.169.254/", "http://10.1.2.3/", "http://224.0.0.1/", "https://user:secret@example.org"])
def test_outbound_private_addresses_rejected(url):
    with pytest.raises(network_policy.UnsafeURL):
        network_policy.validate_url(url)


def test_redirect_revalidated_and_download_bounded(monkeypatch):
    monkeypatch.setattr(network_policy.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    seen = []
    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal"})
    original = httpx.Client
    monkeypatch.setattr(http, "proxy_for", lambda url: None)
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(network_policy.UnsafeURL):
        http.get("https://public.example/", untrusted=True, follow_redirects=True)
    assert len(seen) == 1
    http.close_clients()
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"12345")), **kwargs))
    with pytest.raises(ValueError, match="大小限制"):
        http.get("https://public.example/", untrusted=True, max_bytes=4)
    http.close_clients()


def test_settings_reject_types_and_privileged_changes(app_client):
    for key, value in (("hooks", {"draft.finalized": ["command"]}), ("storage.data_dir", "elsewhere"),
                       ("pipeline.auto", "false"), ("cards.max_chars_per_page", -1)):
        assert app_client.put("/api/settings", json={"key": key, "value": value}).status_code == 422
