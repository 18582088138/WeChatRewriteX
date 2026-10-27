"""测试隔离：独立临时数据目录 + 内存级配置。无 LLM/搜索 key 时全流程走降级路径。"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("wenshu-data")
    os.environ["WENSHU_DATA_DIR"] = str(d)
    # 测试确定性：屏蔽本机/`.env` 中的真实密钥，全流程走降级路径与 FakeLLM
    saved = {}
    for k in ("DEEPSEEK_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
              "TAVILY_API_KEY", "BING_SEARCH_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY",
              "COVERR_API_KEY", "MINIMAX_API_KEY", "MINIMAX_TTS_API_KEY"):
        if k in os.environ:
            saved[k] = os.environ.pop(k)
    yield d
    os.environ.pop("WENSHU_DATA_DIR", None)
    os.environ.update(saved)


@pytest.fixture(scope="session", autouse=True)
def _offline_stubs(_isolated_data_dir):
    """网络面打桩：搜索器与素材库媒体补充在测试中一律走离线路径。"""
    from app.agents import collector as collector_mod
    from app.services.media import stock as stock_mod
    from app.services.search.registry import null_searcher

    orig_get, orig_paper = collector_mod.get_searcher, collector_mod.get_paper_searcher
    orig_enrich = stock_mod.enrich_media
    collector_mod.get_searcher = null_searcher
    collector_mod.get_paper_searcher = null_searcher
    stock_mod.enrich_media = lambda *a, **k: {"images": 0, "videos": 0}
    yield
    collector_mod.get_searcher = orig_get
    collector_mod.get_paper_searcher = orig_paper
    stock_mod.enrich_media = orig_enrich


@pytest.fixture(scope="session", autouse=True)
def _init_db(_isolated_data_dir):
    from app.storage import db
    db.init_db()
    yield


@pytest.fixture()
def app_client():
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(start_worker=True)) as client:
        yield client
