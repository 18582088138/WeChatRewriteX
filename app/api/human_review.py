import json
import secrets
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..storage import db
from ..services import human_review as human, team

router=APIRouter(prefix="/api",tags=["human review"])


class Submit(BaseModel):
    reviewer_id: str
    expected_version: int
    expected_revision: int


class Decision(BaseModel):
    status: str
    reason: str = Field(default="",max_length=4000)
    submission_revision: int
    expected_version: int | None = None
    expected_revision: int | None = None
    reviewer_id: str | None = None


@router.get("/articles/{aid}/human-review")
@db.read_snapshot
def history(aid:str):
    team.require(aid)
    rows=db.query("SELECT * FROM human_submissions WHERE article_id=? ORDER BY created_at DESC",(aid,))
    for row in rows:
        row["doc"]=json.loads(row.pop("doc_json"))
        row.pop("assets_json")
        row["comments"]=db.query("SELECT c.*,m.name FROM human_comments c JOIN members m ON m.id=c.member_id WHERE submission_id=? ORDER BY created_at",(row["id"],))
    from ..services import draft_service
    doc=None
    try: doc,_=draft_service.get_doc(aid)
    except ValueError: pass
    reviewer_rows=db.query("SELECT id,name,login,role,enabled FROM members WHERE enabled=1")
    reviewers=[{k:v for k,v in m.items() if k!='enabled'} for m in reviewer_rows if team.allowed(m,aid,"review")]
    valid=bool(doc and any(r["status"]=='approved' and r["version"]==doc.version and r["edit_revision"]==doc.edit_revision and r["fingerprint"]==human.fingerprint(doc) for r in rows))
    return {"submissions":rows,"reviewers":reviewers,"self_review":human.self_review(),"valid_approval":valid,"member_id":team.actor.get()["id"]}


@router.post("/articles/{aid}/human-review")
def submit(aid:str,body:Submit):
    return human.submit(aid,body.reviewer_id,body.expected_version,body.expected_revision)


@router.put("/articles/{aid}/human-review/{sid}")
def decision(aid:str,sid:str,body:Decision):
    return human.decide(aid,sid,body.status,body.reason,body.submission_revision,body.expected_version,body.expected_revision,body.reviewer_id)


class Comment(BaseModel):
    anchor: str = Field(default="meta",max_length=200)
    message: str = Field(min_length=1,max_length=4000)


@router.post("/articles/{aid}/human-review/{sid}/comments")
def comment(aid:str,sid:str,body:Comment):
    with db.transaction():
        team.require(aid,"review")
        row=human.submission(sid,aid)
        if row["reviewer_id"]!=team.actor.get()["id"]:
            raise HTTPException(403,"仅指派审核者可添加审核意见")
        doc=json.loads(row["doc_json"])
        if body.anchor!='meta' and body.anchor not in [b['id'] for b in doc['blocks']]:
            raise HTTPException(422,"意见锚点不在提交快照中")
        cid=secrets.token_hex(16)
        db.execute("INSERT INTO human_comments(id,submission_id,member_id,anchor,message,created_at) VALUES(?,?,?,?,?,?)",(cid,sid,team.actor.get()["id"],body.anchor,body.message,time.time()))
        team.audit("human.comment",cid,aid,{"submission_id":sid,"anchor":body.anchor})
    return {"id":cid}


class CommentState(BaseModel):
    status: str
    reason: str = Field(default="",max_length=4000)
    expected_revision: int


@router.put("/articles/{aid}/human-review/{sid}/comments/{cid}")
def comment_state(aid:str,sid:str,cid:str,body:CommentState):
    with db.transaction():
        team.require(aid,"write")
        human.submission(sid,aid)
        row=db.query_one("SELECT * FROM human_comments WHERE id=? AND submission_id=?",(cid,sid))
        if not row: raise HTTPException(404,"意见不存在")
        if row['revision']!=body.expected_revision: raise HTTPException(409,"意见处理状态已更新")
        if body.status not in ('pending','resolved','declined') or (body.status=='declined' and not body.reason.strip()):
            raise HTTPException(422,"不采纳须填写原因；状态为 pending/resolved/declined")
        db.execute("UPDATE human_comments SET status=?,reason=?,revision=revision+1 WHERE id=?",(body.status,body.reason.strip(),cid))
        team.audit("human.comment-state",cid,aid,{"status":body.status,"reason":body.reason})
    return {"ok":True}


class TeamSettings(BaseModel):
    self_review: bool


@router.get("/team/settings")
def settings(): return {"self_review":human.self_review()}


@router.put("/team/settings")
def update_settings(body:TeamSettings):
    with db.transaction():
        team.admin()
        db.execute("UPDATE team_settings SET value=? WHERE key='self_review'",('true' if body.self_review else 'false',))
        team.audit("team.settings",detail=body.model_dump())
    return settings()
