"""Run from an empty directory using a freshly installed wheel, never the source tree."""
from pathlib import Path


def main():
    from fastapi.testclient import TestClient
    from app.main import WEB_DIST, create_app
    from app.core import config
    from app.core.models import ArticleStatus, Block, BlockType, DraftDoc
    from app.services import draft_service, workflow
    from app.services.cards.render import render_cards
    from app.storage import dao
    assert WEB_DIST.joinpath("index.html").is_file(), "missing frontend package assets"
    assert (config.CONFIG_DIR / "prompts" / "creator" / "draft.j2").is_file()
    with TestClient(create_app(start_worker=False)) as client:
        assert client.get("/api/ready").status_code == 200
        assert client.get("/").status_code == 200
        env_file = config.RUNTIME_ROOT / ".env"
        original_env = env_file.read_text(encoding="utf-8")
        try:
            env_file.write_text("DEEPSEEK_API_KEY=wheel-test-key\n", encoding="utf-8")
            result = client.post("/api/settings/reload-env")
            assert result.status_code == 200 and result.json()["services"]["llm_purposes"]["create"]
            assert "wheel-test-key" not in result.text
            env_file.write_text("", encoding="utf-8")
            assert client.post("/api/settings/reload-env").status_code == 200
        finally:
            env_file.write_text(original_env, encoding="utf-8")
            assert client.post("/api/settings/reload-env").status_code == 200
        aid = dao.create_article("local://wheel", title="安装包验收")["id"]
        doc = draft_service.save_new_version(DraftDoc(id="", article_id=aid, version=0,
            blocks=[Block(id="b", type=BlockType.PARAGRAPH, text="安装包中的卡片主题、数据库结构和前端资源均可用。")]),
            "agent", checkpoint=True)
        cards = render_cards(aid)
        assert len(cards) == 2 and all(path.stat().st_size > 1000 for path in cards)
        doc.blocks[0].text += " 连续编辑不升正式版本。"
        saved = draft_service.save_new_version(doc, "human")
        assert saved.version == 1 and saved.edit_revision > doc.edit_revision
        dao.set_article_status(aid, ArticleStatus.EDITING)
        assert workflow.finalize(aid, force=True)["version"] == 1
        from app.services.publish.exporter import export_variants
        result = export_variants(aid, ["x", "weibo", "xhs"])
        assert result["ok"]
        assert (Path(result["export_root"]) / "x" / "thread.json").is_file()
        assert not (Path(result["export_root"]) / "runs").exists()
        files = client.get(f"/api/articles/{aid}/exports").json()["files"]
        assert client.get("/files/" + next(p for p in files if p.endswith("post-01.txt"))).status_code == 200
        assert client.get("/files/app.db").status_code == 404
    print("Installed wheel smoke passed: schema, prompts, frontend, cards and file boundary")


if __name__ == "__main__":
    main()
