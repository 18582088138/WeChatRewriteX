"""Run from an empty directory using a freshly installed wheel, never the source tree."""
from pathlib import Path


def main():
    from fastapi.testclient import TestClient
    from app.main import WEB_DIST, create_app
    from app.core import config
    from app.core.models import Block, BlockType, DraftDoc
    from app.services import draft_service
    from app.services.cards.render import render_cards
    from app.storage import dao
    assert WEB_DIST.joinpath("index.html").is_file(), "missing frontend package assets"
    assert (config.CONFIG_DIR / "prompts" / "creator" / "draft.j2").is_file()
    with TestClient(create_app(start_worker=False)) as client:
        assert client.get("/api/ready").status_code == 200
        assert client.get("/").status_code == 200
        aid = dao.create_article("local://wheel", title="安装包验收")["id"]
        draft_service.save_new_version(DraftDoc(id="", article_id=aid, version=0,
            blocks=[Block(id="b", type=BlockType.PARAGRAPH, text="安装包中的卡片主题、数据库结构和前端资源均可用。")]),
            "agent", checkpoint=True)
        cards = render_cards(aid)
        assert cards and all(path.stat().st_size > 1000 for path in cards)
        assert client.get("/files/app.db").status_code == 404
    print("Installed wheel smoke passed: schema, prompts, frontend, cards and file boundary")


if __name__ == "__main__":
    main()
