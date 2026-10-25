"""类型化 DAO。所有 SQL 集中在此，业务层不直接写 SQL。"""
from __future__ import annotations

import json
from typing import Any

from ..core.ids import new_id
from ..core.models import ArticleStatus, ChecklistItem, DraftDoc
from . import db


# ---------- articles ----------

def create_article(url: str, title: str = "", user_notes: str = "",
                   style_pack: str | None = None, target_word_count: int | None = None) -> dict:
    aid = new_id("article")
    db.execute(
        "INSERT INTO articles(id,url,title,user_notes,style_pack,target_word_count) VALUES(?,?,?,?,?,?)",
        (aid, url, title, user_notes, style_pack, target_word_count),
    )
    return get_article(aid)


def get_article(aid: str) -> dict | None:
    return db.query_one("SELECT * FROM articles WHERE id=?", (aid,))


def list_articles(status_ui: str | None = None, q: str | None = None) -> list[dict]:
    rows = db.query("SELECT * FROM articles ORDER BY created_at DESC")
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["title"] or "").lower() or ql in (r["url"] or "").lower()]
    if status_ui:
        from ..core.statemachine import ui_status
        rows = [r for r in rows if ui_status(ArticleStatus(r["status"])) == status_ui]
    return rows


def set_article_status(aid: str, status: ArticleStatus, error: str | None = None) -> None:
    db.execute(
        "UPDATE articles SET status=?, error=?, updated_at=datetime('now','localtime') WHERE id=?",
        (status.value, error, aid),
    )


def update_article(aid: str, **fields: Any) -> None:
    allowed = {"title", "source_site", "published_at", "user_notes", "style_pack", "target_word_count"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sql = "UPDATE articles SET " + ",".join(f"{k}=?" for k in sets) + ", updated_at=datetime('now','localtime') WHERE id=?"
    db.execute(sql, (*sets.values(), aid))


# ---------- materials ----------

def insert_material(**f: Any) -> str:
    mid = f.get("id") or new_id("material")
    db.execute(
        """INSERT OR IGNORE INTO materials
        (id,scope,article_id,kind,path,sha256,phash,source_url,source_material_id,
         watermark,width,height,duration,ref_type,fetch_status,note,title,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            mid, f["scope"], f.get("article_id"), f["kind"], f.get("path"), f.get("sha256"),
            f.get("phash"), f.get("source_url"), f.get("source_material_id"), f.get("watermark"),
            f.get("width"), f.get("height"), f.get("duration"), f.get("ref_type"),
            f.get("fetch_status", "ok"), f.get("note", ""), f.get("title", ""),
            json.dumps(f.get("meta", {}), ensure_ascii=False),
        ),
    )
    return mid


def get_material(mid: str) -> dict | None:
    return db.query_one("SELECT * FROM materials WHERE id=?", (mid,))


def find_material_by_sha(sha256: str) -> dict | None:
    return db.query_one("SELECT * FROM materials WHERE sha256=?", (sha256,))


def list_materials(scope: str | None = None, article_id: str | None = None,
                   kind: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM materials WHERE 1=1", []
    if scope:
        sql += " AND scope=?"; params.append(scope)
    if article_id:
        sql += " AND article_id=?"; params.append(article_id)
    if kind:
        sql += " AND kind=?"; params.append(kind)
    return db.query(sql + " ORDER BY created_at DESC", tuple(params))


def set_material_text(mid: str, content: str) -> None:
    db.execute("INSERT OR REPLACE INTO material_texts(material_id,content) VALUES(?,?)", (mid, content))
    if db.fts_available():
        db.execute("DELETE FROM material_fts WHERE material_id=?", (mid,))
        db.execute("INSERT INTO material_fts(material_id,content) VALUES(?,?)", (mid, content))


def get_material_text(mid: str) -> str:
    row = db.query_one("SELECT content FROM material_texts WHERE material_id=?", (mid,))
    return row["content"] if row else ""


def search_materials_fts(query_str: str, limit: int = 20) -> list[tuple[str, str]]:
    """返回 (material_id, snippet)。FTS 不可用时降级 LIKE。

    MATCH 查询一律转成带引号的短语并转义内部引号，防止标点触发 FTS5 语法错误；
    任何 FTS 错误都回退 LIKE，不让检索失败炸掉审稿。
    """
    def _like() -> list[tuple[str, str]]:
        rows = db.query(
            "SELECT material_id, substr(content,1,200) AS snip "
            "FROM material_texts WHERE content LIKE ? LIMIT ?",
            (f"%{query_str}%", limit),
        )
        return [(r["material_id"], r["snip"]) for r in rows]

    if not db.fts_available():
        return _like()
    phrase = '"' + query_str.replace('"', '""') + '"'
    try:
        rows = db.query(
            "SELECT material_id, snippet(material_fts,1,'','','…',8) AS snip "
            "FROM material_fts WHERE material_fts MATCH ? LIMIT ?",
            (phrase, limit),
        )
        return [(r["material_id"], r["snip"]) for r in rows]
    except Exception:
        return _like()


def all_material_texts(article_id: str | None = None) -> list[tuple[str, str]]:
    if article_id:
        rows = db.query(
            "SELECT t.material_id, t.content FROM material_texts t "
            "JOIN materials m ON m.id=t.material_id WHERE m.article_id=? OR m.scope='common'",
            (article_id,),
        )
    else:
        rows = db.query("SELECT material_id, content FROM material_texts")
    return [(r["material_id"], r["content"]) for r in rows]


# ---------- drafts ----------

def save_draft(doc: DraftDoc, origin: str = "agent", status: str = "editing") -> dict:
    from ..core.blocks import doc_word_count
    db.execute(
        """INSERT INTO drafts(id,article_id,version,doc_json,keywords_json,one_liner,
                              title_candidates_json,word_count,status,parent_version,origin)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc.id, doc.article_id, doc.version, doc.model_dump_json(),
            json.dumps(doc.meta.keywords, ensure_ascii=False), doc.meta.one_liner,
            json.dumps(doc.meta.title_candidates, ensure_ascii=False),
            doc_word_count(doc), status, doc.version - 1 if doc.version > 1 else None, origin,
        ),
    )
    return get_draft(doc.article_id, doc.version)


def get_draft(article_id: str, version: int) -> dict | None:
    cp = checkpoint_at(article_id, version)
    if not cp:
        return None
    if cp["version"] == version:
        return cp
    return _reconstruct(aid=article_id, checkpoint=cp, target_seq=version)


def get_draft_by_id(draft_id: str) -> dict | None:
    return db.query_one("SELECT * FROM drafts WHERE id=?", (draft_id,))


def latest_draft(article_id: str) -> dict | None:
    """当前 HEAD：最近 checkpoint + 后续变更重放（无变更则直接返回 checkpoint）。"""
    cp = latest_checkpoint(article_id)
    if not cp:
        return None
    changes = changes_after(article_id, cp["version"])
    if not changes:
        return cp
    last_seq = changes[-1]["seq"]
    return _reconstruct(article_id, cp, last_seq)


def _reconstruct(article_id: str, checkpoint: dict, target_seq: int) -> dict:
    """checkpoint 快照 + 逐条变更重放到目标版本（块级增量版本的核心）。"""
    import json as _json
    from ..core.models import Block, DraftDoc
    doc = DraftDoc.model_validate_json(checkpoint["doc_json"])
    changes = [c for c in changes_after(article_id, checkpoint["version"])
               if c["seq"] <= target_seq]
    for c in changes:
        op = c["op"]
        if op == "update" or op == "replace_image" or op == "set_caption":
            new = _json.loads(c["new_json"]) if c["new_json"] else None
            if new:
                for i, b in enumerate(doc.blocks):
                    if b.id == c["block_id"]:
                        doc.blocks[i] = Block.model_validate(new)
                        break
        elif op == "insert":
            new = _json.loads(c["new_json"]) if c["new_json"] else None
            if new:
                b = Block.model_validate(new)
                # 插入位置记录在新块 attrs 的 after
                after = (c["new_json"] and _json.loads(c["new_json"]).get("_after")) or None
                doc.blocks.append(b) if after is None else None
                if after is not None:
                    for i, x in enumerate(doc.blocks):
                        if x.id == after:
                            doc.blocks.insert(i + 1, b)
                            break
        elif op == "remove":
            doc.blocks = [b for b in doc.blocks if b.id != c["block_id"]]
        elif op == "meta":
            new = _json.loads(c["new_json"]) if c["new_json"] else None
            if new:
                doc.meta = doc.meta.model_validate({**doc.meta.model_dump(), **new})
    out = dict(checkpoint)
    out["doc_json"] = doc.model_dump_json()
    out["version"] = target_seq
    out["id"] = f"{article_id}-v{target_seq}"
    out["reconstructed"] = True
    return out


def list_drafts(article_id: str) -> list[dict]:
    return db.query(
        "SELECT id,article_id,version,word_count,status,origin,created_at "
        "FROM drafts WHERE article_id=? ORDER BY version DESC", (article_id,))


def next_version(article_id: str) -> int:
    row = db.query_one("SELECT MAX(version) AS v FROM drafts WHERE article_id=?", (article_id,))
    chg = db.query_one("SELECT MAX(seq) AS s FROM draft_changes WHERE article_id=?", (article_id,))
    return max(row["v"] or 0, chg["s"] or 0) + 1


def record_change(article_id: str, seq: int, block_id: str, op: str,
                  old_json: str | None, new_json: str | None, origin: str) -> None:
    db.execute(
        """INSERT INTO draft_changes(article_id,seq,block_id,op,old_json,new_json,origin)
           VALUES(?,?,?,?,?,?,?)""",
        (article_id, seq, block_id, op, old_json, new_json, origin),
    )


def changes_after(article_id: str, after_seq: int) -> list[dict]:
    return db.query(
        "SELECT * FROM draft_changes WHERE article_id=? AND seq>? ORDER BY seq, id",
        (article_id, after_seq))


def latest_checkpoint(article_id: str) -> dict | None:
    return db.query_one(
        "SELECT * FROM drafts WHERE article_id=? ORDER BY version DESC LIMIT 1", (article_id,))


def checkpoint_at(article_id: str, version: int) -> dict | None:
    return db.query_one(
        "SELECT * FROM drafts WHERE article_id=? AND version<=? ORDER BY version DESC LIMIT 1",
        (article_id, version))


def list_draft_versions(article_id: str) -> list[dict]:
    """版本时间线：checkpoint + 每次编辑的变更组，供版本下拉。"""
    cps = db.query(
        "SELECT id, version, origin, status, word_count, created_at FROM drafts "
        "WHERE article_id=?", (article_id,))
    out = [{"version": c["version"], "origin": c["origin"], "status": c["status"],
            "word_count": c["word_count"], "created_at": c["created_at"],
            "checkpoint": True, "draft_id": c["id"]} for c in cps]
    groups = db.query(
        "SELECT seq, origin, MIN(created_at) AS created_at, COUNT(*) AS n FROM draft_changes "
        "WHERE article_id=? GROUP BY seq ORDER BY seq DESC", (article_id,))
    for g in groups:
        out.append({"version": g["seq"], "origin": g["origin"], "status": "",
                    "word_count": None, "created_at": g["created_at"],
                    "checkpoint": False, "changes": g["n"]})
    out.sort(key=lambda x: -x["version"])
    return out


def set_draft_status(draft_id: str, status: str) -> None:
    db.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))


# ---------- reviews ----------

def create_review(article_id: str, draft_id: str, draft_version: int,
                  report_items: list[ChecklistItem], scores: dict) -> str:
    rid = new_id("review")
    db.execute(
        "INSERT INTO reviews(id,article_id,draft_id,draft_version,scores_json) VALUES(?,?,?,?,?)",
        (rid, article_id, draft_id, draft_version, json.dumps(scores, ensure_ascii=False)),
    )
    for it in report_items:
        db.execute(
            """INSERT INTO review_items(id,review_id,category,severity,block_id,message,
                                       suggestion,evidence_json,auto_fixable)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (rid2 := new_id("review_item"), rid, it.category, it.severity, it.block_id,
             it.message, it.suggestion, json.dumps(it.evidence, ensure_ascii=False),
             1 if it.auto_fixable else 0),
        )
        it.id = rid2
    return rid


def latest_review(article_id: str) -> dict | None:
    return db.query_one(
        "SELECT * FROM reviews WHERE article_id=? ORDER BY created_at DESC LIMIT 1", (article_id,))


def list_review_items(review_id: str) -> list[dict]:
    return db.query("SELECT * FROM review_items WHERE review_id=? ORDER BY "
                    "CASE severity WHEN 'blocker' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END",
                    (review_id,))


def set_review_item_status(item_id: str, status: str, note: str | None = None,
                           resolved_by: str = "human") -> None:
    db.execute(
        "UPDATE review_items SET status=?, resolved_note=?, resolved_by=? WHERE id=?",
        (status, note, resolved_by, item_id),
    )


def pending_blockers(review_id: str) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM review_items WHERE review_id=? AND severity='blocker' "
        "AND status IN ('pending','accepted')", (review_id,))
    return row["c"]


# ---------- jobs ----------

def enqueue_job(job_type: str, article_id: str | None = None, payload: dict | None = None) -> str:
    jid = new_id("job")
    db.execute(
        "INSERT INTO jobs(id,type,article_id,payload_json) VALUES(?,?,?,?)",
        (jid, job_type, article_id, json.dumps(payload or {}, ensure_ascii=False)),
    )
    return jid


def claim_job(types: tuple[str, ...] | None = None) -> dict | None:
    """原子认领任务（UPDATE...RETURNING，多线程安全）。types 限定泳道。"""
    with db.connect() as conn:
        if types:
            marks = ",".join("?" for _ in types)
            row = conn.execute(
                f"""UPDATE jobs SET status='running', attempts=attempts+1,
                    updated_at=datetime('now','localtime')
                    WHERE id = (SELECT id FROM jobs WHERE status='pending'
                                AND run_after<=strftime('%s','now') AND type IN ({marks})
                                ORDER BY created_at LIMIT 1)
                    RETURNING *""",
                types).fetchone()
        else:
            row = conn.execute(
                """UPDATE jobs SET status='running', attempts=attempts+1,
                   updated_at=datetime('now','localtime')
                   WHERE id = (SELECT id FROM jobs WHERE status='pending'
                               AND run_after<=strftime('%s','now')
                               ORDER BY created_at LIMIT 1)
                   RETURNING *""").fetchone()
        conn.commit()
        return dict(row) if row else None


def finish_job(jid: str, result: dict | None = None) -> None:
    db.execute(
        "UPDATE jobs SET status='done', result_json=?, updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(result or {}, ensure_ascii=False), jid),
    )


def fail_job(jid: str, error: str, requeue: bool = False) -> None:
    status = "pending" if requeue else "failed"
    db.execute(
        "UPDATE jobs SET status=?, error=?, updated_at=datetime('now','localtime') WHERE id=?",
        (status, error, jid),
    )


def list_jobs(article_id: str | None = None, limit: int = 50) -> list[dict]:
    if article_id:
        return db.query("SELECT * FROM jobs WHERE article_id=? ORDER BY created_at DESC LIMIT ?",
                        (article_id, limit))
    return db.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))


# ---------- llm_calls / settings / publish ----------

def log_llm_call(article_id: str | None, stage: str, channel: str, model: str,
                 prompt_tokens: int, completion_tokens: int, latency_ms: int,
                 cost_est: float, ok: bool) -> None:
    db.execute(
        """INSERT INTO llm_calls(article_id,stage,channel,model,prompt_tokens,
                                 completion_tokens,latency_ms,cost_est,ok)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (article_id, stage, channel, model, prompt_tokens, completion_tokens, latency_ms,
         cost_est, 1 if ok else 0),
    )


def db_settings() -> dict[str, Any]:
    return {r["key"]: json.loads(r["value_json"]) for r in db.query("SELECT * FROM settings")}


def set_setting(key: str, value: Any) -> None:
    db.execute("INSERT OR REPLACE INTO settings(key,value_json) VALUES(?,?)",
               (key, json.dumps(value, ensure_ascii=False)))


def create_publish_job(article_id: str, draft_id: str, platform: str,
                       variant: dict, target_id: str | None = None) -> str:
    pid = new_id("publish_job")
    db.execute(
        "INSERT INTO publish_jobs(id,article_id,draft_id,target_id,platform,variant_json) "
        "VALUES(?,?,?,?,?,?)",
        (pid, article_id, draft_id, target_id, platform, json.dumps(variant, ensure_ascii=False)),
    )
    return pid


def finish_publish_job(pid: str, result: dict, ok: bool = True) -> None:
    db.execute(
        "UPDATE publish_jobs SET status=?, result_json=? WHERE id=?",
        ("done" if ok else "failed", json.dumps(result, ensure_ascii=False), pid),
    )


def list_publish_jobs(article_id: str) -> list[dict]:
    return db.query("SELECT * FROM publish_jobs WHERE article_id=? ORDER BY created_at DESC",
                    (article_id,))
