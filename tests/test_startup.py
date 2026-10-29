import os
from pathlib import Path
import subprocess
import sys
import threading

def test_slow_import_scan_does_not_block_ready(monkeypatch):
    from app.services import imports
    from app.main import create_app
    from fastapi.testclient import TestClient
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_scan():
        started.set()
        assert release.wait(10)
        finished.set()

    monkeypatch.setattr(imports, "scan_once", slow_scan)
    try:
        with TestClient(create_app(start_worker=False)) as client:
            assert started.wait(1)
            assert client.get("/api/ready").status_code == 200
            assert not finished.is_set()
            release.set()
    finally:
        release.set()
    assert finished.is_set()
    assert imports._IMPORT_THREAD is None


def test_web_startup_does_not_import_heavy_article_parser():
    subprocess.run([sys.executable, "-X", "utf8", "-c",
                    "import app.main, sys; assert 'trafilatura' not in sys.modules; assert 'app.agents.collector' not in sys.modules"],
                   cwd=Path(__file__).resolve().parents[1], check=True, env=os.environ.copy(), timeout=30)
