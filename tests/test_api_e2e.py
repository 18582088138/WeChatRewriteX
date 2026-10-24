"""API 冒烟 + 无 LLM 降级全流程：fixture 文章 → 收集 → 洗稿(降级稿) → 审稿 → 编辑 → 定稿。"""
from __future__ import annotations

import time

from app.storage import dao


def _wait_status(client, aid: str, want: set[str], timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        art = client.get(f"/api/articles/{aid}").json()
        if art["status"] in want:
            return art
        time.sleep(0.4)
    raise AssertionError(f"等待状态 {want} 超时，当前: {art['status']} {art.get('error')}")


def test_full_flow_degraded(app_client):
    # 1. 录入（自动触发收集；fixture:// 走离线 fixture）
    r = app_client.post("/api/articles", json={"url": "fixture://sample_article.md"})
    assert r.status_code == 200, r.text
    aid = r.json()["article"]["id"]
    assert r.json()["article"]["ui_status"] == "New"

    # 2. 收集完成（无搜索 key → scarce，仅原文）
    art = _wait_status(app_client, aid, {"COLLECTED"})
    assert art["materials_count"] >= 1
    mats = app_client.get(f"/api/articles/{aid}/materials?scope=article").json()["materials"]
    assert any(m["ref_type"] == "primary" for m in mats)

    # 3. 手动推进洗稿（无 LLM → 降级稿，版本 v1 落盘）
    r = app_client.post(f"/api/articles/{aid}/advance", json={"stage": "rewrite"})
    assert r.status_code == 200
    art = _wait_status(app_client, aid, {"DRAFTED"})
    draft = app_client.get(f"/api/articles/{aid}/draft").json()["draft"]
    assert draft["version"] == 1 and len(draft["doc"]["blocks"]) >= 2

    # 4. 审稿（规则维度生效）
    r = app_client.post(f"/api/articles/{aid}/advance", json={"stage": "review"})
    assert r.status_code == 200
    _wait_status(app_client, aid, {"EDITING"})
    rev = app_client.get(f"/api/articles/{aid}/reviews/latest").json()
    assert rev["review"] and "items" in rev
    assert any(i["category"] in ("layout", "originality", "compliance")
               for i in rev["items"])

    # 5. 人工编辑：改一段 → 产生 v2
    para = next(b for b in draft["doc"]["blocks"] if b["type"] == "paragraph")
    r = app_client.put(f"/api/drafts/{draft['id']}/edit",
                       json={"ops": [{"op": "update", "block_id": para["id"],
                                      "text": "人工修订后的段落，内容完全不同，避免撞稿。"}]})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2

    # 6. 定稿（降级稿与原文有重合，可能撞 blocker：先尝试，不行则强制定稿并留痕）
    r = app_client.post(f"/api/articles/{aid}/finalize", json={"force": False})
    if r.status_code == 409:
        r = app_client.post(f"/api/articles/{aid}/finalize", json={"force": True})
        assert r.status_code == 200 and r.json()["forced_blockers"] >= 1
    else:
        assert r.status_code == 200
    art = app_client.get(f"/api/articles/{aid}").json()
    assert art["ui_status"] == "Done"

    # 7. 导出发布包（wechat_mp + weibo + x；xhs 卡片需 Playwright，单独测）
    r = app_client.post(f"/api/articles/{aid}/publish",
                        json={"platforms": ["wechat_mp", "weibo", "x"]})
    assert r.status_code == 200
    _wait_status(app_client, aid, {"DONE"})
    jobs = app_client.get(f"/api/articles/{aid}/publish-jobs").json()["jobs"]
    assert {j["platform"] for j in jobs} == {"wechat_mp", "weibo", "x"}
    assert all(j["status"] == "done" for j in jobs)
    exports = app_client.get(f"/api/articles/{aid}/exports").json()["files"]
    assert any(f.endswith("article.html") for f in exports)
    assert any(f.endswith("README.txt") for f in exports)


def test_settings_and_health(app_client):
    r = app_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["collect"]["search_window_days"] == 3
    assert body["llm_available"] is False          # 测试环境无 key
    r = app_client.put("/api/settings", json={"key": "collect.search_window_days",
                                              "value": 5})
    assert r.status_code == 200
    from app.core import config
    assert config.get("collect.search_window_days") == 5
    dao.set_setting("collect.search_window_days", 3)  # 还原，避免影响其他测试
    config.reload()
