"""测试隔离：独立临时数据目录 + 内存级配置。无 LLM/搜索 key 时全流程走降级路径。"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("wra-data")
    os.environ["WRA_DATA_DIR"] = str(d)
    # 测试确定性：屏蔽本机/`.env` 中的真实密钥，全流程走降级路径与 FakeLLM
    saved = {}
    for k in ("DEEPSEEK_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY",
              "BING_SEARCH_KEY"):
        if k in os.environ:
            saved[k] = os.environ.pop(k)
    yield d
    os.environ.pop("WRA_DATA_DIR", None)
    os.environ.update(saved)


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
