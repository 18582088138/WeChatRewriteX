"""外部项目文件夹导入（V1.14）：识别 → 重建 article/materials/draft + 幂等 + 状态推断。"""
from __future__ import annotations

import json
from pathlib import Path

from app.core import config
from app.services import imports as imp
from app.storage import dao


def _make_project(root: Path, name: str = "外部测试文章-20261028-1200") -> Path:
    d = root / name
    ref = d / "reference" / "样本文章"
    ref.mkdir(parents=True)
    (ref / "content.md").write_text(
        "# 样本标题\n\n这是外部项目文件夹里的正文，内容足够独特。", encoding="utf-8")
    (ref / "meta.json").write_text(json.dumps(
        {"url": "https://example.com/a", "title": "样本文章",
         "published_at": "2026-10-01", "site": "示例站"}), encoding="utf-8")
    (ref / "page.html").write_text("<html></html>", encoding="utf-8")
    (d / "drafts").mkdir()
    doc = {"id": "art_other-v1", "article_id": "art_other", "version": 1,
           "blocks": [
               {"id": "b1", "type": "heading", "level": 1, "text": "样本标题",
                "asset_id": None, "caption": "", "citations": []},
               {"id": "b2", "type": "paragraph", "text": "外部导入的一段正文。",
                "asset_id": None, "caption": "", "citations": []}],
           "meta": {}}
    (d / "drafts" / "v001.json").write_text(json.dumps(doc, ensure_ascii=False),
                                            encoding="utf-8")
    return d


def test_import_external_project_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    _make_project(tmp_path)
    out = imp.scan_once()
    assert len(out["imported"]) == 1
    aid = out["imported"][0]["article_id"]

    art = dao.get_article(aid)
    assert art["lib_dir"] == "外部测试文章-20261028-1200"
    assert art["title"] == "外部测试文章"        # 标题以项目文件夹（拟定标题）为准
    assert art["url"] == "https://example.com/a"
    assert art["status"] == "DRAFTED"           # 有草稿 → 可继续审稿/编辑/定稿

    mats = dao.list_materials(article_id=aid, kind="text")
    assert len(mats) == 1 and mats[0]["ref_type"] == "primary"
    assert "外部项目文件夹里的正文" in dao.get_material_text(mats[0]["id"])

    draft = dao.latest_draft(aid)
    assert draft and "外部导入的一段正文" in draft["doc_json"]

    # 幂等：重复扫描不重复导入
    out2 = imp.scan_once()
    assert not out2["imported"]
    assert out2["skipped"] == ["外部测试文章-20261028-1200"]
