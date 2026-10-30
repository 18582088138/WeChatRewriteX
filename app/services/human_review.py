"""Human decisions bind immutable content and material metadata, independently of AI."""
import hashlib
import json
import secrets
import time
from fastapi import HTTPException
from ..storage import db, dao
from . import team, assets, draft_service

SCHEMA = """
CREATE TABLE IF NOT EXISTS human_submissions(id TEXT PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),
 submitter_id TEXT NOT NULL REFERENCES members(id),reviewer_id TEXT NOT NULL REFERENCES members(id),
 version INTEGER NOT NULL,edit_revision INTEGER NOT NULL,fingerprint TEXT NOT NULL,doc_json TEXT NOT NULL,
 assets_json TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,decided_at REAL);
CREATE INDEX IF NOT EXISTS idx_human_article ON human_submissions(article_id,created_at DESC);
CREATE TABLE IF NOT EXISTS human_comments(id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES human_submissions(id),
 member_id TEXT NOT NULL REFERENCES members(id),anchor TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
 reason TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS human_finalizations(snapshot_id TEXT PRIMARY KEY,submission_id TEXT REFERENCES human_submissions(id),
 member_id TEXT NOT NULL,exception_reason TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL,assets_json TEXT NOT NULL,created_at REAL NOT NULL);
"""


def migrate():
    with db.connect() as conn:
        previous = conn.execute("PRAGMA user_version").fetchone()[0]
        if previous < 5:
            import sqlite3
            target_path = db.db_path().parent / "backups" / "before-schema-v5.sqlite3"
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if not target_path.exists():
                target = sqlite3.connect(target_path)
                try:
                    conn.backup(target)
                finally:
                    target.close()
            conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "INSERT OR IGNORE INTO schema_migrations(version) VALUES(5); PRAGMA user_version=5; COMMIT;")
        if previous < 6:
            conn.executescript("""BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS edit_leases(article_id TEXT PRIMARY KEY,member_id TEXT NOT NULL,client_id TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS job_activity(job_id TEXT PRIMARY KEY,member_id TEXT,started_at REAL,finished_at REAL);
INSERT OR IGNORE INTO schema_migrations(version) VALUES(6); PRAGMA user_version=6; COMMIT;
""")


def fingerprint(doc, view=None):
    view = assets.manifest(doc) if view is None else view
    # Locations may change on project rename. Content and descriptive metadata matter.
    stable = {mid: {k: v for k, v in m.items() if k not in ("path", "created_at")} for mid,m in view.items()}
    return hashlib.sha256(json.dumps([draft_service.content_hash(doc),stable],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def current(aid, version, revision):
    doc, _ = draft_service.get_doc(aid)
    if version is None or revision is None:
        raise HTTPException(428, "需携带当前文稿 version 与 revision")
    if doc.version != version:
        raise draft_service.VersionConflict("文稿版本已更新")
    draft_service.check_revision(doc, revision)
    return doc


def submission(sid, aid):
    row = db.query_one("SELECT * FROM human_submissions WHERE id=? AND article_id=?", (sid,aid))
    if not row:
        raise HTTPException(404,"人工提交不存在")
    return row


def submit(aid, reviewer_id, version, revision):
    with db.transaction():
        team.require(aid,"write")
        doc = current(aid,version,revision)
        reviewer = db.query_one("SELECT * FROM members WHERE id=? AND enabled=1",(reviewer_id,))
        if not team.allowed(reviewer,aid,"review"):
            raise HTTPException(422,"审核者需具备本项目审核权限")
        if reviewer_id == team.actor.get()["id"] and not self_review():
            raise HTTPException(403,"团队已禁用自审")
        view = assets.manifest(doc); digest = fingerprint(doc,view)
        old = db.query_one("SELECT * FROM human_submissions WHERE article_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(aid,))
        if old and old["fingerprint"]==digest and old["reviewer_id"]==reviewer_id and old["version"]==version and old["edit_revision"]==revision:
            return old
        db.execute("UPDATE human_submissions SET status='superseded',revision=revision+1 WHERE article_id=? AND status='pending'",(aid,))
        sid = secrets.token_hex(16)
        db.execute("INSERT INTO human_submissions(id,article_id,submitter_id,reviewer_id,version,edit_revision,fingerprint,doc_json,assets_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'pending',?)",
            (sid,aid,team.actor.get()["id"],reviewer_id,version,revision,digest,doc.model_dump_json(),json.dumps(view,ensure_ascii=False),time.time()))
        team.audit("human.submit",sid,aid,{"version":version,"revision":revision,"reviewer_id":reviewer_id,"self_review":reviewer_id==team.actor.get()["id"]})
        return submission(sid,aid)


def self_review():
    return db.query_one("SELECT value FROM team_settings WHERE key='self_review'")["value"] == "true"


def decide(aid,sid,status,reason,expected_revision,version,revision,reviewer_id=None):
    with db.transaction():
        row=submission(sid,aid); member=team.actor.get()
        if row["revision"] != expected_revision:
            # A repeated decision with identical intent is safe; a stale different intent conflicts.
            if row["status"]==status and row["reason"]==reason and row["revision"]==expected_revision+1 and row["reviewer_id"]==member["id"]:
                return row
            raise HTTPException(409,"人工审核状态已改变")
        if row["status"] != "pending":
            raise HTTPException(409,"提交已处理或撤回")
        if status in ("approved","returned"):
            team.require(aid,"review")
            if row["reviewer_id"] != member["id"]:
                raise HTTPException(403,"仅被指派审核者可批准或退回")
            if row["submitter_id"]==member["id"] and not self_review():
                raise HTTPException(403,"团队已禁用自审")
            doc=current(aid,version,revision)
            if doc.version != row["version"] or doc.edit_revision != row["edit_revision"] or fingerprint(doc)!=row["fingerprint"]:
                raise HTTPException(409,"提交内容已过期，请重新提交")
            if status=="returned" and not reason.strip():
                raise HTTPException(422,"退回须说明修改原因")
        elif status in ("withdrawn","reassigned"):
            team.require(aid,"write")
            if member["id"]!=row["submitter_id"] and not team.allowed(member,aid,"manage"):
                raise HTTPException(403,"仅提交人或项目负责人可撤回/改派")
            if status=="reassigned":
                reviewer=db.query_one("SELECT * FROM members WHERE id=? AND enabled=1",(reviewer_id,))
                if not team.allowed(reviewer,aid,"review"):
                    raise HTTPException(422,"新审核者无审核权限")
                if reviewer_id==row["submitter_id"] and not self_review():
                    raise HTTPException(403,"团队已禁用自审")
                db.execute("UPDATE human_submissions SET reviewer_id=? WHERE id=?",(reviewer_id,sid))
        else:
            raise HTTPException(422,"无效审核动作")
        db.execute("UPDATE human_submissions SET status=?,revision=revision+1,reason=?,decided_at=? WHERE id=?",("pending" if status=="reassigned" else status,reason.strip(),time.time(),sid))
        team.audit("human."+status,sid,aid,{"reason":reason.strip(),"reviewer_id":reviewer_id})
        return submission(sid,aid)


def approval(aid,doc,exception_reason=""):
    team.require(aid,"release")
    digest=fingerprint(doc)
    row=db.query_one("SELECT * FROM human_submissions WHERE article_id=? AND version=? AND edit_revision=? AND fingerprint=? AND status='approved' ORDER BY decided_at DESC LIMIT 1",
        (aid,doc.version,doc.edit_revision,digest))
    if exception_reason:
        team.admin()
        if len(exception_reason.strip()) < 5:
            raise HTTPException(422,"管理员例外须至少5字符的具体原因")
        team.audit("human.exception",aid,aid,{"reason":exception_reason.strip(),"version":doc.version,"revision":doc.edit_revision})
        return None
    if not row:
        raise HTTPException(409,"当前内容尚未获得有效人工批准；AI审稿不等于人工批准")
    return row


def record_final(doc,row,exception_reason):
    db.execute("INSERT OR IGNORE INTO human_finalizations VALUES(?,?,?,?,?,?,?)",(doc.id,row["id"] if row else None,team.actor.get()["id"],exception_reason.strip(),fingerprint(doc),json.dumps(assets.manifest(doc),ensure_ascii=False),time.time()))
    team.audit("draft.finalize",doc.id,doc.article_id,{"submission_id":row["id"] if row else None})


def export_approval(aid,draft,view=None):
    if not team.enabled():
        return None
    from ..core.models import DraftDoc
    team.require(aid,"release")
    row=db.query_one("SELECT * FROM human_finalizations WHERE snapshot_id=?",(draft["id"],))
    if not row or draft["status"]!="finalized" or row["fingerprint"]!=fingerprint(DraftDoc.model_validate_json(draft["doc_json"]), view):
        raise HTTPException(409,"定稿缺少人工批准或素材已变更，需重新审核定稿（管理员可注明例外原因）")
    return json.loads(row["assets_json"])
