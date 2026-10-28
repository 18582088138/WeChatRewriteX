"""文章与流水线控制路由。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import config, events
from ..core.models import ArticleStatus
from ..core.statemachine import ui_status
from ..pipeline import orchestrator, queue
from ..storage import dao, db

router = APIRouter(prefix="/api/articles", tags=["articles"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateArticle(BaseModel):
    url: str = ""                  # 本地文件收集模式可空（title 必填）
    title: str = ""                # 本地模式：文件夹/主题名
    user_notes: str = ""
    style_pack: str | None = None
    target_word_count: int | None = None
    auto_collect: bool = True


class Finalize(BaseModel):
    expected_version: int | None = None
    force: bool = False


def _shape(row: dict) -> dict:
    out = dict(row)
    st = ArticleStatus(row["status"])
    out["ui_status"] = ui_status(st)
    out["progress"] = queue.progress(row["id"])
    return out


@router.post("")
def create_article(body: CreateArticle) -> dict:
    url = body.url.strip()
    if not url and not body.title.strip():
        raise HTTPException(400, "链接模式需填 url；本地文件模式需填 title（主题名）")
    if not url:
        # 本地文件收集：无 URL 可抓，文章以主题名立档，素材由批量上传进入
        url = f"local://{body.title.strip()[:40]}"
    art = dao.create_article(url, title=body.title.strip(), user_notes=body.user_notes,
                             style_pack=body.style_pack,
                             target_word_count=body.target_word_count)
    events.bus.publish(events.ARTICLE_ADDED, art["id"])
    job_id = None
    if body.auto_collect and body.url.strip():
        job_id = queue.enqueue("collect", art["id"])
    return {"article": _shape(art), "collect_job": job_id}


@router.get("")
def list_articles(status: str | None = None, q: str | None = None) -> dict:
    rows = dao.list_articles(status_ui=status if status in ("New", "Process", "Done") else None,
                             q=q)
    return {"articles": [_shape(r) for r in rows]}


@router.get("/{aid}")
def article_detail(aid: str) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    out = _shape(art)
    out["materials_count"] = len(dao.list_materials(article_id=aid))
    out["versions"] = dao.list_drafts(aid)
    out["latest_review"] = dao.latest_review(aid)
    out["publish_jobs"] = dao.list_publish_jobs(aid)
    import json as _json
    try:
        out["selected_material_ids"] = _json.loads(art.get("selected_json") or "[]")
    except Exception:
        out["selected_material_ids"] = []
    return out


class Advance(BaseModel):
    stage: str          # collect | create | review
    selected_material_ids: list[str] | None = None   # create 阶段: 勾选参与创作的素材


class Selection(BaseModel):
    material_ids: list[str]


@router.put("/{aid}/selection")
def set_selection(aid: str, body: Selection) -> dict:
    """保存创作会话的勾选素材集合（左侧素材浏览窗口数据源）。"""
    if not dao.get_article(aid):
        raise HTTPException(404, "文章不存在")
    import json
    db.execute("UPDATE articles SET selected_json=? WHERE id=?",
               (json.dumps(body.material_ids, ensure_ascii=False), aid))
    return {"ok": True, "count": len(body.material_ids)}


@router.post("/{aid}/advance")
def advance(aid: str, body: Advance) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    if body.stage not in ("collect", "create", "review"):
        raise HTTPException(400, "stage 必须是 collect/create/review")
    status = ArticleStatus(art["status"])
    if not orchestrator.can_start(body.stage, status):
        raise HTTPException(409, f"当前状态 {status.value} 不能启动 {body.stage}")
    if body.stage == "create":
        texts = [m for m in dao.list_materials(article_id=aid, kind="text")
                 if m["fetch_status"] == "ok"]
        if not texts:
            raise HTTPException(409, "素材库为空，先完成收集")
    if body.stage == "review" and not dao.latest_draft(aid):
        raise HTTPException(409, "没有草稿，先完成创作")
    payload = {}
    if body.selected_material_ids:
        payload["selected_material_ids"] = body.selected_material_ids
    job_id = queue.enqueue(body.stage, aid, payload)
    return {"job_id": job_id, "stage": body.stage}


@router.post("/{aid}/exports/reveal")
def reveal_export_dir(aid: str, body: RevealExport) -> dict:
    """在系统文件管理器中打开平台发布包文件夹（exports/<platform>/）。"""
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    from ..storage import library
    if body.platform not in ("wechat_mp", "xhs", "weibo", "x"):
        raise HTTPException(400, "未知平台")
    import json
    job = next((j for j in dao.list_publish_jobs(aid) if j["platform"] == body.platform), None)
    d = library.exports_dir(aid) / body.platform
    if job and job["status"] == "done":
        d = Path(json.loads(job["result_json"]).get("export_dir") or str(d))
    if not d.resolve().is_relative_to(library.exports_dir(aid).resolve()):
        raise HTTPException(400, "导出路径无效")
    if not d.is_dir():
        raise HTTPException(404, f"{body.platform} 发布包还没生成——先点「生成发布包」")
    import subprocess
    import sys as _sys
    try:
        if _sys.platform == "win32":
            subprocess.Popen(["explorer", str(d)])
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])
    except OSError as e:
        raise HTTPException(500, f"打开文件夹失败: {e}")
    return {"ok": True, "folder": str(d)}


class RevealExport(BaseModel):
    platform: str


@router.post("/{aid}/finalize")
def finalize(aid: str, body: Finalize) -> dict:
    from ..services import workflow
    try:
        return workflow.finalize(aid, body.force, body.expected_version)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/{aid}/reopen")
def reopen(aid: str) -> dict:
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    cur = ArticleStatus(art["status"])
    if cur not in (ArticleStatus.FINALIZED, ArticleStatus.DONE):
        raise HTTPException(409, "仅定稿/完成后可回炉编辑")
    dao.set_article_status(aid, ArticleStatus.EDITING)
    return {"ok": True}


@router.post("/{aid}/deepsearch")
def deepsearch(aid: str) -> dict:
    """深度搜索（反馈 3.3）：基于已提取主题的新一轮检索，仅增量补充 reference。"""
    art = dao.get_article(aid)
    if not art:
        raise HTTPException(404, "文章不存在")
    if ArticleStatus(art["status"]) not in (ArticleStatus.COLLECTED, ArticleStatus.DRAFTED,
                                            ArticleStatus.REVIEWED, ArticleStatus.EDITING):
        raise HTTPException(409, "请先完成初次收集")
    job_id = queue.enqueue("deepsearch", aid)
    return {"job_id": job_id}


@jobs_router.get("")
def list_jobs(article_id: str | None = None, limit: int = 50) -> dict:
    return {"jobs": dao.list_jobs(article_id, limit)}
