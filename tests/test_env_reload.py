"""V1.16 acceptance: live configuration, authentication and startup isolation."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import threading

import httpx
import pytest

from app.core import config
from app.core.environment import Environment


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "APP_ACCESS_TOKEN", "WENSHU_HTTP_PROXY", "ENV_TEST"):
        monkeypatch.setenv(key, "")
    manager = Environment()
    monkeypatch.setattr(config, "environment", manager)
    monkeypatch.setattr(config, "RUNTIME_ROOT", tmp_path)
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    return path, manager


def test_env_reload_replaces_deletes_and_interpolates(env_file, monkeypatch):
    path, manager = env_file
    monkeypatch.setenv("ENV_TEST", "shell")
    manager.baseline["ENV_TEST"] = "shell"
    path.write_text('ENV_TEST="first\nline"\nDEEPSEEK_API_KEY=${ENV_TEST}\n', encoding="utf-8-sig")
    config.reload_env()
    assert config.get_env("DEEPSEEK_API_KEY") == "first\nline"
    path.write_text("ENV_TEST=second\nDEEPSEEK_API_KEY=${ENV_TEST}\n", encoding="utf-8")
    config.reload_env()
    assert config.get_env("DEEPSEEK_API_KEY") == "second"
    path.write_text("", encoding="utf-8")
    config.reload_env()
    assert config.get_env("DEEPSEEK_API_KEY") is None
    assert config.get_env("ENV_TEST") == "shell"


@pytest.mark.parametrize("text", ['DEEPSEEK_API_KEY=new\nENV_TEST="unclosed', 'DEEPSEEK_API_KEY=new\nENV_TEST', 'DEEPSEEK_API_KEY=new\nENV_TEST=a\x00b'])
def test_env_parse_failure_is_atomic_and_redacted(env_file, text):
    path, manager = env_file
    path.write_text("DEEPSEEK_API_KEY=before", encoding="utf-8")
    config.reload_env()
    path.write_text(text, encoding="utf-8")
    generation = manager.generation
    with pytest.raises(ValueError) as error:
        config.reload_env()
    assert config.get_env("DEEPSEEK_API_KEY") == "before"
    assert "unclosed" not in str(error.value)
    assert manager.generation == generation


def test_restart_only_settings_and_remote_token_are_guarded(env_file):
    path, manager = env_file
    path.write_text("DEEPSEEK_API_KEY=new\nWENSHU_DATA_DIR=different", encoding="utf-8")
    with pytest.raises(ValueError, match="重启"):
        config.reload_env()
    assert not config.get_env("DEEPSEEK_API_KEY")
    manager.require_token = True
    path.write_text("APP_ACCESS_TOKEN=", encoding="utf-8")
    with pytest.raises(ValueError, match="远程绑定"):
        config.reload_env()


@pytest.mark.parametrize("key,value", [("WENSHU_RUNTIME_DIR", "new-root"), ("WENSHU_MIN_FREE_MB", "2")])
def test_deployment_settings_cannot_hot_switch(env_file, key, value):
    path, manager = env_file
    path.write_text(f"DEEPSEEK_API_KEY=new\n{key}={value}", encoding="utf-8")
    with pytest.raises(ValueError, match="重启"):
        config.reload_env()
    assert not config.get_env("DEEPSEEK_API_KEY")
    assert manager.generation == 0


def test_reload_api_immediately_changes_actual_model_authorization(env_file, app_client, monkeypatch):
    from app.services.llm import router
    path, _ = env_file
    seen = []

    @contextmanager
    def fake_client(*args, **kwargs):
        def respond(request):
            seen.append(request.headers["Authorization"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            yield client

    monkeypatch.setattr(router, "client_for", fake_client)
    monkeypatch.setattr(router, "_log", lambda *a, **kw: None)
    for key in ("first-key", "second-key"):
        path.write_text(f"DEEPSEEK_API_KEY={key}", encoding="utf-8")
        response = app_client.post("/api/settings/reload-env")
        assert response.status_code == 200
        assert response.json()["services"]["llm_purposes"]["create"]
        assert key not in response.text
        assert router.complete("create", [{"role": "user", "content": "test"}]).text == "ok"
    assert seen == ["Bearer first-key", "Bearer second-key"]
    path.unlink()
    assert app_client.post("/api/settings/reload-env").status_code == 422
    assert config.get_env("DEEPSEEK_API_KEY") == "second-key"


def test_token_rotation_preserves_authorized_session_without_secret_response(env_file, app_client):
    path, _ = env_file
    path.write_text("APP_ACCESS_TOKEN=old-token", encoding="utf-8")
    config.reload_env()
    assert app_client.get("/api/session", headers={"Authorization": "Bearer old-token"}).status_code == 200
    path.write_text("APP_ACCESS_TOKEN=new-token", encoding="utf-8")
    result = app_client.post("/api/settings/reload-env")
    assert result.status_code == 200 and result.json()["token_changed"]
    assert "new-token" not in result.text
    assert app_client.get("/api/settings").status_code == 200
    app_client.cookies.clear()
    assert app_client.get("/api/session", headers={"Authorization": "Bearer old-token"}).status_code == 401
    assert app_client.get("/api/session", headers={"Authorization": "Bearer new-token"}).status_code == 200
