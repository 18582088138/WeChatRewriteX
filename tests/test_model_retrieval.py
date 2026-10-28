import copy
import hashlib
import json

import pytest

from app.core import config
from app.services.llm import router
from app.services.rag import index
from app.storage import dao, db, library


def test_purpose_capability_and_cross_provider_fallback(monkeypatch):
    settings = copy.deepcopy(config.all_settings())
    settings["llm"]["channels"] = [{"name": "one", "provider": "deepseek", "env_key": "TEST_LLM_A"},
                                    {"name": "two", "provider": "openai", "env_key": "TEST_LLM_B"}]
    settings["llm"]["routing"]["create"] = {"model": "deepseek/deepseek-chat", "fallback_models": ["openai/test-model"]}
    settings["llm"]["routing"]["review"] = {"model": "volcengine/no-channel"}
    monkeypatch.setenv("TEST_LLM_A", "a")
    monkeypatch.setenv("TEST_LLM_B", "b")
    calls = []
    def chat(channel, model, *args, **kwargs):
        calls.append(channel["name"])
        if channel["name"] == "one":
            raise router.LLMError("unavailable")
        return {"choices": [{"message": {"content": "fallback"}}], "usage": {"prompt_tokens": 10}}
    monkeypatch.setattr(router, "_chat", chat)
    with config.using_snapshot(settings):
        assert router.available("create") and not router.available("review")
        result = router.complete("create", [{"role": "user", "content": "test"}])
    assert calls == ["one", "two"]
    assert result.model == "openai/test-model" and result.cost_est is None


def test_fts_and_embedding_share_article_scope_and_cache_identity(monkeypatch):
    first = dao.create_article("local://first")["id"]
    second = dao.create_article("local://second")["id"]
    mid = library.ingest_text("architecture needle first", "first", "article", first)
    other = library.ingest_text("architecture needle second", "second", "article", second)
    common = library.ingest_text("architecture needle common", "common", "common")
    found = {m for m, _ in dao.search_materials_fts("needle", 20, first)}
    assert mid in found and common in found and other not in found
    class Embedder:
        available = True
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return [[1.0, 0.0] for text in texts]
    emb = Embedder()
    monkeypatch.setattr(index, "get_embedder", lambda: emb)
    settings = copy.deepcopy(config.all_settings())
    settings["llm"]["embedding"] = {"model": "test/one", "dimension": 2}
    with config.using_snapshot(settings):
        assert index.index_materials([mid]) == 1
        assert index.index_materials([mid]) == 0
    settings["llm"]["embedding"]["model"] = "test/two"
    with config.using_snapshot(settings):
        assert index.index_materials([mid]) == 1  # same dimension, different model
        dao.set_material_text(mid, "new evidence")
        assert db.query_one("SELECT * FROM embeddings WHERE material_id=?", (mid,)) is None
        assert index.index_materials([mid]) == 1
    assert emb.calls == 3


def test_recovery_does_not_repeat_committed_creation(monkeypatch):
    from app.agents.creator import CreatorAgent
    from app.core.execution import context
    from app.core.models import ArticleStatus
    aid = dao.create_article("local://recovery")["id"]
    library.ingest_text("offline content", "recovery", "article", aid)
    dao.set_article_status(aid, ArticleStatus.CREATING)
    token = context.set({"job_id": "recovery-test"})
    try:
        agent = CreatorAgent()
        first = agent.run(aid)
        second = agent.run(aid)
        assert second.id == first.id and dao.next_version(aid) == 2
    finally:
        context.reset(token)
