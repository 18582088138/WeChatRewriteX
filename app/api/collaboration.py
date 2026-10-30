"""Project membership and explicit sharing; team roles never grant implicit projects."""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..storage import db, dao
from ..services import team

router = APIRouter(prefix="/api", tags=["collaboration"])


class Grant(BaseModel):
    member_id: str
    can_create: bool = False
    can_review: bool = False


class AccessChange(BaseModel):
    expected_revision: int
    owner_id: str
    archived: bool = False
    members: list[Grant] = Field(default_factory=list)


@router.get("/articles/{aid}/access")
def access(aid: str):
    team.require(aid)
    row = db.query_one("SELECT * FROM project_access WHERE article_id=?", (aid,))
    if not row:
        raise HTTPException(404, "团队项目尚未初始化")
    grants = db.query("SELECT p.*,m.name,m.login FROM project_members p JOIN members m ON m.id=p.member_id WHERE article_id=?", (aid,))
    member = team.actor.get()
    capabilities = {cap: team.allowed(member, aid, cap) for cap in ("read", "write", "review", "manage", "release")}
    # Names are intentionally visible to teammates; credentials are never returned.
    candidates = db.query("SELECT id,name,login,role FROM members WHERE enabled=1") if capabilities["manage"] else []
    return {**row, "members": grants, "candidates": candidates, "capabilities": capabilities}


@router.put("/articles/{aid}/access")
def change_access(aid: str, body: AccessChange):
    with db.transaction():
        team.require(aid, "manage")
        old = db.query_one("SELECT * FROM project_access WHERE article_id=?", (aid,))
        if not old or old["revision"] != body.expected_revision:
            raise HTTPException(409, "项目权限已更新，请刷新后重试")
        owner = db.query_one("SELECT id FROM members WHERE id=? AND enabled=1", (body.owner_id,))
        if not owner:
            raise HTTPException(422, "负责人必须是可用成员")
        ids = [g.member_id for g in body.members]
        if len(ids) != len(set(ids)) or len(ids) > 100:
            raise HTTPException(422, "项目成员重复或过多")
        for mid in ids:
            if not db.query_one("SELECT id FROM members WHERE id=? AND enabled=1", (mid,)):
                raise HTTPException(422, "成员已禁用或不存在")
        db.execute("UPDATE project_access SET owner_id=?,archived=?,revision=revision+1 WHERE article_id=?", (body.owner_id, body.archived, aid))
        db.execute("DELETE FROM project_members WHERE article_id=?", (aid,))
        for g in body.members:
            db.execute("INSERT INTO project_members VALUES(?,?,?,?)", (aid,g.member_id,g.can_create,g.can_review))
        team.audit("project.access", aid, aid, body.model_dump())
    # Transfer may revoke this caller: don't read back with their old authorization.
    return {"ok": True, "revision": body.expected_revision+1}


class Sharing(BaseModel):
    shared: bool


@router.put("/materials/{mid}/sharing")
def sharing(mid: str, body: Sharing):
    with db.transaction():
        team.admin()
        material = dao.get_material(mid)
        if not material or material["scope"] != "common":
            raise HTTPException(422, "仅公共库素材可显式共享，请先复制到公共库")
        if body.shared:
            db.execute("INSERT OR IGNORE INTO shared_materials VALUES(?)", (mid,))
        else:
            db.execute("DELETE FROM shared_materials WHERE material_id=?", (mid,))
        team.audit("material.share", mid, detail={"shared": body.shared})
    return {"ok": True}


@router.post("/articles/{aid}/access/adopt-jobs")
def adopt_jobs(aid: str):
    """Administrator explicitly takes responsibility for legacy unfinished jobs."""
    with db.transaction():
        team.admin()
        team.require(aid)
        count = 0
        for job in dao.list_jobs(aid, 1000):
            payload = json.loads(job.get("payload_json") or "{}")
            if payload.get("_member_id") or job["status"] not in ("pending", "failed"):
                continue
            payload["_member_id"] = team.actor.get()["id"]
            db.execute("UPDATE jobs SET payload_json=?,status='pending',error=NULL,run_after=0 WHERE id=?", (json.dumps(payload),job["id"]))
            team.audit("job.adopt", job["id"], aid)
            count += 1
    return {"adopted": count}
