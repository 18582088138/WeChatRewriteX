"""草稿版本路由：编辑 / 段落重生成 / 资料融合插入 / 版本回滚。

块级增量版本（V1.2）：一切修改只记变更块差异；checkpoint 仅落在创建/定稿/回滚。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.models import BlockType, DraftDoc
from ..services import draft_service
from ..storage import dao, library

router = APIRouter(prefix="/api", tags=["drafts"])


class EditOps(BaseModel):
    ops: list[dict]           # [{op: update|remove|replace_image|set_caption|update_meta|insert_after, ...}]


class Regenerate(BaseModel):
    block_ids: list[str]
    instruction: str = ""


class InsertRefs(BaseModel):
    material_ids: list[str]
    after_block_id: str | None = None
    instruction: str = ""


class Rollback(BaseModel):
    version: int


def _doc_view(article_id: str, version: int | None = None) -> dict:
    doc, row = draft_service.get_doc(article_id, version)
    return {"draft": {**{k: row[k] for k in
                         ("id", "article_id", "version", "word_count", "status",
                          "origin", "created_at")},
                      "doc": doc.model_dump()},
            "versions": dao.list_draft_versions(article_id)}


@router.get("/articles/{aid}/draft")
def get_draft(aid: str, version: int | None = None) -> dict:
    try:
        return _doc_view(aid, version)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/articles/{aid}/versions")
def versions(aid: str) -> dict:
    return {"versions": dao.list_draft_versions(aid)}


@router.post("/articles/{aid}/rollback")
def rollback_draft(aid: str, body: Rollback) -> dict:
    try:
        doc = draft_service.rollback(aid, body.version)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"version": doc.version, "rolled_back_to": body.version,
            "word_count": doc.meta.word_count}


@router.put("/drafts/{draft_id}/edit")
def edit_draft(draft_id: str, body: EditOps) -> dict:
    row = dao.get_draft_by_id(draft_id)
    if not row:
        raise HTTPException(404, "草稿不存在")
    aid = row["article_id"]
    old = DraftDoc.model_validate_json(row["doc_json"])
    new = old.model_copy(deep=True)
    changed = draft_service.apply_ops(new, body.ops)
    if not changed:
        raise HTTPException(400, "没有生效的修改")

    # 标题联动（反馈 1.4）：改主标题 → 同步正文一级标题块 + 项目文件夹改名
    title_op = next((o for o in body.ops
                     if o.get("op") == "update_meta" and o.get("field") == "title_selected"),
                    None)
    folder_renamed = False
    if title_op and title_op.get("value"):
        for b in new.blocks:
            if b.type == BlockType.HEADING and b.level == 1:
                b.text = title_op["value"]
                break
        library.rename_to_created_title(aid, title_op["value"])
        folder_renamed = True

    saved = draft_service.save_new_version(new, origin="human")
    recheck = draft_service.maybe_recheck(aid, old, saved)
    return {"draft_id": saved.id, "version": saved.version,
            "recheck_enqueued": recheck, "folder_renamed": folder_renamed}


@router.post("/drafts/{draft_id}/regenerate")
def regenerate(draft_id: str, body: Regenerate) -> dict:
    row = dao.get_draft_by_id(draft_id)
    if not row:
        raise HTTPException(404, "草稿不存在")
    if not body.block_ids:
        raise HTTPException(400, "block_ids 不能为空")
    old = DraftDoc.model_validate_json(row["doc_json"])
    from ..agents.creator import CreatorAgent
    agent = CreatorAgent()
    if not agent.llm_available():
        raise HTTPException(503, "未配置 LLM 渠道，无法 AI 重写")
    new = old.model_copy(deep=True)
    try:
        new = agent.regenerate_blocks(row["article_id"], new, body.block_ids, body.instruction)
    except Exception as e:
        raise HTTPException(502, f"重写失败: {e}")
    saved = draft_service.save_new_version(new, origin="auto_fix")
    recheck = draft_service.maybe_recheck(saved.article_id, old, saved)
    return {"draft_id": saved.id, "version": saved.version, "recheck_enqueued": recheck}


@router.post("/drafts/{draft_id}/insert-refs")
def insert_refs(draft_id: str, body: InsertRefs) -> dict:
    row = dao.get_draft_by_id(draft_id)
    if not row:
        raise HTTPException(404, "草稿不存在")
    if not body.material_ids:
        raise HTTPException(400, "material_ids 不能为空")
    from ..agents.creator import CreatorAgent
    agent = CreatorAgent()
    if not agent.llm_available():
        raise HTTPException(503, "未配置 LLM 渠道，无法融合插入")
    new = DraftDoc.model_validate_json(row["doc_json"]).model_copy(deep=True)
    try:
        new = agent.insert_references(row["article_id"], new, body.material_ids,
                                      body.after_block_id, body.instruction)
    except Exception as e:
        raise HTTPException(502, f"融合插入失败: {e}")
    saved = draft_service.save_new_version(new, origin="insert_refs")
    return {"draft_id": saved.id, "version": saved.version}
