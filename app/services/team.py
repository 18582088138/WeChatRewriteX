"""Single-team identity, revocable sessions and project authorization."""
from contextvars import ContextVar
import hashlib
import hmac
import json
import os
import secrets
import time
import unicodedata

from fastapi import HTTPException
from ..storage import db

actor = ContextVar("member", default=None)
operation = ContextVar("authorized_operation", default=None)
write_guard = ContextVar("project_write_guard", default=None)
_active = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','maintainer','member')),
 enabled INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 0, must_change INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS member_sessions(id TEXT PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id),
 version INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(id TEXT PRIMARY KEY, since REAL NOT NULL, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS project_access(article_id TEXT PRIMARY KEY REFERENCES articles(id),
 owner_id TEXT NOT NULL REFERENCES members(id), archived INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS project_members(article_id TEXT REFERENCES articles(id), member_id TEXT REFERENCES members(id),
 can_create INTEGER NOT NULL DEFAULT 0, can_review INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(article_id,member_id));
CREATE TABLE IF NOT EXISTS team_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO team_settings VALUES('self_review','true');
CREATE TABLE IF NOT EXISTS shared_materials(material_id TEXT PRIMARY KEY REFERENCES materials(id));
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT, article_id TEXT,
 action TEXT NOT NULL, object_id TEXT, detail_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
"""


def enabled():
    return _active or os.environ.get("WENSHU_TEAM_MODE") == "1"


def migrate():
    global _active
    with db.connect() as conn:
        previous = conn.execute("PRAGMA user_version").fetchone()[0]
        if previous < 4:
            if conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]:
                from pathlib import Path
                import sqlite3
                backup = db.db_path().parent / "backups" / "before-schema-v4.sqlite3"
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    target = sqlite3.connect(backup)
                    try:
                        conn.backup(target)
                    finally:
                        target.close()
            conn.executescript("BEGIN IMMEDIATE;" + SCHEMA +
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES(4); PRAGMA user_version=4; COMMIT;")
    _active = True


def password_hash(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise HTTPException(422, "密码须为10～256个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify(password, stored):
    try:
        kind, salt, digest = stored.split("$")
        if kind != "scrypt" or len(password) > 256 or len(salt) != 32 or len(digest) != 64:
            return False
        result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(result.hex(), digest)
    except (ValueError, TypeError):
        return False


def public(member):
    return {k: member[k] for k in ("id", "login", "name", "role", "enabled", "must_change")}


def create_member(login, name, password, role="member", reset=False):
    login = unicodedata.normalize("NFKC", login).strip().casefold()
    if not login or len(login) > 64 or not all(c.isascii() and (c.isalnum() or c in "_.-") for c in login):
        raise HTTPException(422, "登录名仅允许字母、数字、点、下划线或短横线，最多64字符")
    if role not in ("admin", "maintainer", "member") or not name.strip() or len(name) > 80:
        raise HTTPException(422, "成员名称或等级无效")
    hashed = password_hash(password)
    mid = secrets.token_hex(16)
    with db.transaction():
        if db.query_one("SELECT id FROM members WHERE login=?", (login,)):
            raise HTTPException(409, "登录名已存在")
        db.execute("INSERT INTO members(id,login,name,password_hash,role,must_change) VALUES(?,?,?,?,?,?)",
                   (mid, login, name.strip(), hashed, role, int(reset)))
        audit("member.create", mid, detail={"role": role})
    return public(db.query_one("SELECT * FROM members WHERE id=?", (mid,)))


def initialize_admin(login, name, password):
    with db.transaction():
        if db.query_one("SELECT id FROM members LIMIT 1"):
            raise HTTPException(409, "管理员已初始化")
        member = create_member(login, name, password, "admin")
        claim_legacy(member["id"])
        return member


def recover_admin(login, password):
    """Offline CLI only; caller must own the OS runtime lock. No HTTP equivalent."""
    login = unicodedata.normalize("NFKC", login).strip().casefold()
    hashed = password_hash(password)
    with db.transaction():
        member = db.query_one("SELECT id FROM members WHERE login=?", (login,))
        if not member:
            raise ValueError("恢复账号不存在；新实例请使用 --init-admin")
        db.execute("UPDATE members SET password_hash=?,role='admin',enabled=1,must_change=1,session_version=session_version+1 WHERE id=?",(hashed,member['id']))
        db.execute("DELETE FROM member_sessions WHERE member_id=?",(member['id'],))
        audit("member.offline-recovery",member['id'])


def claim_legacy(mid):
    db.execute("INSERT OR IGNORE INTO project_access(article_id,owner_id) SELECT id,? FROM articles", (mid,))


def session(token):
    if not token:
        return None
    return db.query_one("SELECT m.*,s.csrf,s.id AS sid FROM member_sessions s JOIN members m ON m.id=s.member_id "
        "WHERE s.id=? AND s.expires>? AND s.version=m.session_version AND m.enabled=1",
        (hashlib.sha256(token.encode()).hexdigest(), time.time()))


def login(login_name, password, ip):
    normalized = unicodedata.normalize("NFKC", login_name).strip().casefold()
    now = time.time()
    keys = [(hashlib.sha256((ip+normalized).encode()).hexdigest(), 10),
            (hashlib.sha256(("ip:"+ip).encode()).hexdigest(), 40)]
    with db.transaction():
        for key, limit in keys:
            row = db.query_one("SELECT * FROM auth_attempts WHERE id=?", (key,))
            if row and row["since"] > now-900 and row["count"] >= limit:
                raise HTTPException(429, "登录尝试过多，请稍后重试")
            db.execute("INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET "
                "count=CASE WHEN since<? THEN 1 ELSE count+1 END, since=CASE WHEN since<? THEN excluded.since ELSE since END",
                (key, now, now-900, now-900))
    member = db.query_one("SELECT * FROM members WHERE login=? AND enabled=1", (normalized,))
    # Comparable work for unknown accounts; never expose existence in errors.
    hashed = member["password_hash"] if member else "scrypt$" + "00"*16 + "$" + "00"*32
    if not verify(password, hashed):
        raise HTTPException(401, "登录名或密码错误")
    raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sid = hashlib.sha256(raw.encode()).hexdigest()
    with db.transaction():
        db.execute("DELETE FROM member_sessions WHERE expires<?", (now,))
        db.execute("INSERT INTO member_sessions VALUES(?,?,?,?,?)", (sid, member["id"], member["session_version"], csrf, now+28800))
        db.execute("DELETE FROM auth_attempts WHERE id=?", (keys[0][0],))
        audit("session.login", member["id"])
    return raw, csrf, public(member)


def allowed(member, aid, capability="read"):
    if not member or not member.get("enabled"):
        return False
    if member["role"] == "admin":
        return True
    access = db.query_one("SELECT * FROM project_access WHERE article_id=?", (aid,))
    grant = db.query_one("SELECT * FROM project_members WHERE article_id=? AND member_id=?", (aid, member["id"]))
    owner = bool(access and access["owner_id"] == member["id"])
    if not owner and not grant:
        return False
    if capability == "read":
        return True
    if not access or access["archived"]:
        return capability == "manage" and owner
    if capability == "manage":
        return owner
    if capability == "release":
        return member["role"] == "maintainer" and (owner or bool(grant["can_create"]))
    return owner or bool(grant["can_create" if capability == "write" else "can_review"])


def require(aid, capability="read", member=None):
    member = member or actor.get()
    if enabled() and not allowed(member, aid, capability):
        raise HTTPException(404, "项目不存在或无访问权限")


def admin():
    if not actor.get() or actor.get()["role"] != "admin":
        raise HTTPException(403, "仅管理员可执行")


def recheck():
    member = actor.get()
    if not enabled() or not member:
        return
    current = db.query_one("SELECT * FROM members WHERE id=? AND enabled=1", (member["id"],))
    if not current or current["session_version"] != member["session_version"]:
        raise HTTPException(401, "成员会话已失效")
    if member.get("sid") and not db.query_one("SELECT id FROM member_sessions WHERE id=? AND expires>?", (member["sid"], time.time())):
        raise HTTPException(401, "成员会话已退出")
    op = operation.get()
    if op:
        if op[0] == "admin":
            if current["role"] != "admin":
                raise HTTPException(403, "管理权限已撤销")
        elif op[0]:
            require(op[0], op[1], current)
    guard = write_guard.get()
    if guard:
        row = db.query_one("SELECT revision FROM project_access WHERE article_id=?", (guard["aid"],))
        if not row or row["revision"] != guard["revision"]:
            raise HTTPException(409, "项目已被其他成员更新；保留本地输入，刷新核对后重试")


def advance_guard():
    guard = write_guard.get()
    if guard:
        db.execute("UPDATE project_access SET revision=revision+1 WHERE article_id=?", (guard["aid"],))
        return guard["revision"] + 1
    return None


def visibility(column="id"):
    member = actor.get()
    if not enabled() or not member or member["role"] == "admin":
        return "1=1", ()
    return (f"({column} IN (SELECT article_id FROM project_access WHERE owner_id=?) OR "
            f"{column} IN (SELECT article_id FROM project_members WHERE member_id=?))", (member["id"], member["id"]))


def material_allowed(member, material):
    return bool(material and (allowed(member, material["article_id"]) if material["scope"] == "article" else
        member and (member["role"] == "admin" or db.query_one("SELECT material_id FROM shared_materials WHERE material_id=?", (material["id"],)))))


def material_visibility(prefix=""):
    member = actor.get()
    if not enabled() or not member or member["role"] == "admin":
        return "1=1", ()
    clause, params = visibility(prefix + "article_id")
    return (f"(({prefix}scope='article' AND {clause}) OR ({prefix}scope='common' AND "
            f"{prefix}id IN (SELECT material_id FROM shared_materials)))", params)


def audit(action, object_id=None, aid=None, detail=None):
    if enabled():
        member = actor.get()
        db.execute("INSERT INTO audit_events(member_id,article_id,action,object_id,detail_json,created_at) VALUES(?,?,?,?,?,?)",
            (member["id"] if member else None, aid, action, object_id, json.dumps(detail or {}, ensure_ascii=False), time.time()))
