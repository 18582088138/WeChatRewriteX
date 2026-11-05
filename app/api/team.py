"""Account and team management endpoints; no public registration."""
import hmac
import os
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from ..services import team
from ..storage import db

router = APIRouter(prefix="/api/auth", tags=["members"])


class Credentials(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)


class Bootstrap(Credentials):
    name: str = Field(max_length=80)
    token: str = Field(max_length=256)


@router.get("/status")
def status():
    return {"team_mode": team.enabled(), "initialized": bool(team.enabled() and db.query_one("SELECT id FROM members LIMIT 1"))}


@router.post("/bootstrap")
def bootstrap(body: Bootstrap):
    if not team.enabled():
        raise HTTPException(404)
    token = os.environ.get("WENSHU_BOOTSTRAP_TOKEN", "")
    if len(token) < 24 or not hmac.compare_digest(token, body.token):
        raise HTTPException(403, "初始化凭据无效；也可在主机使用本地管理员初始化命令")
    return team.initialize_admin(body.login, body.name, body.password)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    if not team.enabled():
        raise HTTPException(404)
    raw, csrf, member = team.login(body.login, body.password, request.client.host)
    response.set_cookie("wenshu_member", raw, max_age=28800, httponly=True, secure=request.url.scheme == "https", samesite="strict")
    return {"member": member, "csrf": csrf}


@router.get("/me")
def me():
    member = team.actor.get()
    if not member:
        raise HTTPException(401, "请登录成员账号")
    return {"member": team.public(member), "csrf": member["csrf"]}


@router.post("/logout")
def logout(response: Response):
    db.execute("DELETE FROM member_sessions WHERE id=?", (team.actor.get()["sid"],))
    response.delete_cookie("wenshu_member")
    return {"ok": True}


class Password(BaseModel):
    old_password: str = Field(max_length=256)
    password: str = Field(max_length=256)


@router.post("/password")
def password(body: Password, response: Response):
    member = team.actor.get()
    if not team.verify(body.old_password, member["password_hash"]):
        raise HTTPException(403, "当前密码错误")
    hashed = team.password_hash(body.password)
    with db.transaction():
        db.execute("UPDATE members SET password_hash=?,session_version=session_version+1,must_change=0 WHERE id=?", (hashed, member["id"]))
        team.audit("member.password", member["id"])
    response.delete_cookie("wenshu_member")
    return {"ok": True, "login_required": True}


class Member(Credentials):
    name: str = Field(max_length=80)
    role: str = "member"


@router.get("/members")
def members():
    team.admin()
    return {"members": [team.public(m) for m in db.query("SELECT * FROM members ORDER BY login")]}


@router.post("/members")
def add(body: Member):
    team.admin()
    return team.create_member(body.login, body.name, body.password, body.role, reset=True)


class ChangeMember(BaseModel):
    role: str
    enabled: bool
    password: str | None = Field(default=None, max_length=256)


@router.put("/members/{mid}")
def change(mid: str, body: ChangeMember):
    team.admin()
    if body.role not in ("admin", "maintainer", "member"):
        raise HTTPException(422, "成员等级无效")
    hashed = team.password_hash(body.password) if body.password else None
    with db.transaction():
        old = db.query_one("SELECT * FROM members WHERE id=?", (mid,))
        if not old:
            raise HTTPException(404)
        if old["role"] == "admin" and old["enabled"] and (body.role != "admin" or not body.enabled):
            if db.query_one("SELECT COUNT(*) AS n FROM members WHERE enabled=1 AND role='admin'")["n"] <= 1:
                raise HTTPException(409, "不能撤销最后一个可用管理员")
        if not body.enabled and db.query_one("SELECT article_id FROM project_access WHERE owner_id=? LIMIT 1", (mid,)):
            raise HTTPException(409, "请先转移其负责的项目")
        db.execute("UPDATE members SET role=?,enabled=?,session_version=session_version+1 WHERE id=?", (body.role, int(body.enabled), mid))
        if hashed:
            db.execute("UPDATE members SET password_hash=?,must_change=1 WHERE id=?", (hashed, mid))
        team.audit("member.change", mid, detail={"role": body.role, "enabled": body.enabled, "password_reset": bool(hashed)})
    return {"ok": True}
