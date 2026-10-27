"""API 冒烟 + 无 LLM 降级全流程：fixture 文章 → 收集 → 创作(降级稿) → 审稿 → 编辑 → 定稿。"""
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

    # 3. 手动推进创作（无 LLM → 降级稿，版本 v1 落盘）
    r = app_client.post(f"/api/articles/{aid}/advance", json={"stage": "create"})
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


def _drafted_article(client, tag: str = "") -> str:
    """fixture 离线链路走到 REVIEWED（收集→创作→审稿，全降级模式）。

    tag：同分钟跑多个 fixture 文章时标题会撞项目文件夹名（标题-分钟 粒度），
    用 tag 改标题隔离文件夹。"""
    r = client.post("/api/articles", json={"url": "fixture://sample_article.md"})
    assert r.status_code == 200, r.text
    aid = r.json()["article"]["id"]
    if tag:
        from app.storage import db
        db.execute("UPDATE articles SET title=?, lib_dir=NULL WHERE id=?", (f"sample_{tag}", aid))
    _wait_status(client, aid, {"COLLECTED"})
    client.post(f"/api/articles/{aid}/advance", json={"stage": "create"})
    _wait_status(client, aid, {"DRAFTED"})
    client.post(f"/api/articles/{aid}/advance", json={"stage": "review"})
    _wait_status(client, aid, {"REVIEWED", "EDITING"})
    return aid


def test_finalize_version_node(app_client):
    """V1.7 版本机制：定稿=正式版本快照（进回滚列表）；定稿幂等；定稿后可编辑；
    编辑后再次定稿生成全新独立版本。"""
    aid = _drafted_article(app_client)

    # 定稿 → 生成 finalized 快照
    r = app_client.post(f"/api/articles/{aid}/finalize", json={"force": False})
    assert r.status_code == 200, r.text
    v1 = r.json()["version"]
    assert app_client.get(f"/api/articles/{aid}").json()["status"] == "FINALIZED"
    vers = app_client.get(f"/api/articles/{aid}/versions").json()["versions"]
    finals = [v for v in vers if v.get("checkpoint") and v["origin"] == "finalized"]
    assert len(finals) == 1 and finals[0]["saved"] is True

    # 已定稿再定稿 → 幂等，不重复产版本
    r = app_client.post(f"/api/articles/{aid}/finalize", json={})
    assert r.json().get("already_finalized") is True
    vers2 = app_client.get(f"/api/articles/{aid}/versions").json()["versions"]
    assert len([v for v in vers2 if v.get("checkpoint") and v["origin"] == "finalized"]) == 1

    # 定稿后继续编辑：直接成功且状态自动回 EDITING
    draft = app_client.get(f"/api/articles/{aid}/draft").json()["draft"]
    para = next(b for b in draft["doc"]["blocks"] if b["type"] == "paragraph")
    r = app_client.put(f"/api/drafts/{draft['id']}/edit",
                       json={"ops": [{"op": "update", "block_id": para["id"],
                                      "text": "定稿后还能继续改的一段话。"}]})
    assert r.status_code == 200, r.text
    assert app_client.get(f"/api/articles/{aid}").json()["status"] == "EDITING"

    # 再次定稿 → 全新独立版本，回滚列表两个定稿快照
    r = app_client.post(f"/api/articles/{aid}/finalize", json={})
    v2 = r.json()["version"]
    assert v2 > v1
    vers3 = app_client.get(f"/api/articles/{aid}/versions").json()["versions"]
    finals3 = [v for v in vers3 if v.get("checkpoint") and v["origin"] == "finalized"]
    assert len(finals3) == 2 and {f["version"] for f in finals3} == {v1, v2}

    # 可回滚到第一次定稿
    r = app_client.post(f"/api/articles/{aid}/rollback", json={"version": v1})
    assert r.status_code == 200


def test_local_batch_upload_classification(app_client):
    """本地文件收集模式：无链接立档 → 批量上传自动识别类型分流 → 状态直达 COLLECTED。"""
    import io
    from PIL import Image

    r = app_client.post("/api/articles",
                        json={"title": "本地测试集", "auto_collect": False})
    assert r.status_code == 200, r.text
    art = r.json()["article"]
    assert art["url"].startswith("local://")

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 30, 30)).save(buf, "PNG")
    files = [
        ("files", ("笔记.md", "# 标题\n\n正文内容。".encode(), "text/markdown")),
        ("files", ("图.png", buf.getvalue(), "image/png")),
        ("files", ("片.mp4", b"\x00\x00\x00\x18ftypmp42fake", "video/mp4")),
        ("files", ("附件.xyz", b"unknown-bytes", "application/octet-stream")),
    ]
    r = app_client.post(f"/api/articles/{art['id']}/materials/upload-batch", files=files)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] == 4 and len(out["ok"]) == 4 and not out["failed"]

    mats = app_client.get(f"/api/articles/{art['id']}/materials?scope=article").json()["materials"]
    kinds = {m["title"].split(".")[0].split("-")[-1]: m["kind"] for m in mats}
    assert set(m["kind"] for m in mats) == {"text", "image", "video", "doc"}
    # 文本素材正文进了可检索库（FTS 证据源）
    text_m = next(m for m in mats if m["kind"] == "text")
    content = app_client.get(f"/api/materials/{text_m['id']}/text").json()["content"]
    assert "正文内容" in content
    # 本地收集：上传即完成收集
    assert app_client.get(f"/api/articles/{art['id']}").json()["status"] == "COLLECTED"


def test_exports_reveal_and_publish_progress(app_client, monkeypatch):
    """exports/reveal：未生成时 404；生成后返回文件夹路径（Popen 打桩防真弹窗）。"""
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    aid = _drafted_article(app_client, tag="reveal")
    r = app_client.post(f"/api/articles/{aid}/exports/reveal", json={"platform": "weibo"})
    assert r.status_code == 404                      # 还没生成
    app_client.post(f"/api/articles/{aid}/finalize", json={"force": True})
    r = app_client.post(f"/api/articles/{aid}/publish", json={"platforms": ["weibo"]})
    assert r.status_code == 200
    _wait_status(app_client, aid, {"DONE"})
    r = app_client.post(f"/api/articles/{aid}/exports/reveal", json={"platform": "weibo"})
    assert r.status_code == 200 and r.json()["folder"].endswith("weibo")
    r = app_client.post(f"/api/articles/{aid}/exports/reveal", json={"platform": "xhs"})
    assert r.status_code in (200, 404)               # xhs 未勾选导出则 404
