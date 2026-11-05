"""Project membership and explicit sharing; team roles never grant implicit projects."""
import json
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..storage import db, dao
from ..services import team

router = APIRouter(prefix="/api", tags=["collaboration"])


@router.get("/articles/{aid}/audit")
def project_audit(aid:str):
    team.require(aid)
    return {"events": db.query("SELECT a.*,m.name FROM audit_events a LEFT JOIN members m ON m.id=a.member_id WHERE article_id=? ORDER BY a.id DESC LIMIT 200",(aid,))}


@router.get("/team/audit")
def team_audit():
    team.admin()
    return {"events": db.query("SELECT a.*,m.name FROM audit_events a LEFT JOIN members m ON m.id=a.member_id ORDER BY a.id DESC LIMIT 200")}


@router.get("/team/work")
def work():
    member=team.actor.get(); clause,params=team.visibility("s.article_id")
    review=db.query("SELECT s.id,s.article_id,s.version,s.edit_revision,s.status,a.title FROM human_submissions s JOIN articles a ON a.id=s.article_id WHERE "+clause+" AND s.reviewer_id=? AND s.status='pending' ORDER BY s.created_at DESC",(*params,member['id']))
    returned=db.query("SELECT s.id,s.article_id,s.reason,a.title FROM human_submissions s JOIN articles a ON a.id=s.article_id WHERE "+clause+" AND s.submitter_id=? AND s.status='returned' AND s.id=(SELECT id FROM human_submissions WHERE article_id=s.article_id ORDER BY created_at DESC LIMIT 1)",(*params,member['id']))
    from .articles import list_jobs
    jobs=list_jobs(limit=200)['jobs']
    return {'review':review,'returned':returned,'failed':[j for j in jobs if j['status']=='failed']}


class Lease(BaseModel):
    client_id: str = Field(min_length=8,max_length=100)


@router.get("/articles/{aid}/lease")
def lease(aid:str):
    team.require(aid)
    return {"lease":db.query_one("SELECT l.*,m.name FROM edit_leases l JOIN members m ON m.id=l.member_id WHERE l.article_id=? AND l.expires>? AND m.enabled=1",(aid,time.time()))}


@router.post("/articles/{aid}/lease")
def occupy(aid:str,body:Lease):
    with db.transaction():
        team.require(aid,'write')
        old=lease(aid)['lease']
        if old and (old['member_id']!=team.actor.get()['id'] or old['client_id']!=body.client_id):
            return {'lease':old,'acquired':False}
        db.execute("INSERT INTO edit_leases VALUES(?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET member_id=excluded.member_id,client_id=excluded.client_id,expires=excluded.expires",(aid,team.actor.get()['id'],body.client_id,time.time()+60))
    return {**lease(aid),'acquired':True}


@router.delete("/articles/{aid}/lease/{client_id}")
def release_lease(aid:str,client_id:str):
    with db.transaction():
        team.require(aid,'write')
        db.execute('DELETE FROM edit_leases WHERE article_id=? AND member_id=? AND client_id=?',(aid,team.actor.get()['id'],client_id))
    return {'ok':True}


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
