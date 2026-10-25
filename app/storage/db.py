"""SQLite 连接与初始化。同步 sqlite3 + FastAPI 同步路由(threadpool)，本地单用户足够。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core.config import data_dir

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
_db_path: Path | None = None
_fts_available: bool | None = None


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = data_dir() / "app.db"
    return _db_path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(_SCHEMA)
        # 轻量迁移：老库补 lib_dir 列 + sha256 唯一索引降级为普通索引
        for ddl in ("ALTER TABLE articles ADD COLUMN lib_dir TEXT",
                    "ALTER TABLE articles ADD COLUMN selected_json TEXT DEFAULT '[]'",
                    "ALTER TABLE drafts ADD COLUMN note TEXT DEFAULT ''"):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("DROP INDEX IF EXISTS idx_materials_sha")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_sha ON materials(sha256)")
        except sqlite3.OperationalError:
            pass
        _init_fts(conn)


def _init_fts(conn: sqlite3.Connection) -> None:
    """FTS5 trigram 对中文子串检索友好（SQLite≥3.34）；不可用时标记降级为 LIKE。"""
    global _fts_available
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS material_fts "
            "USING fts5(material_id UNINDEXED, content, tokenize='trigram')"
        )
        _fts_available = True
    except sqlite3.Error:
        _fts_available = False


def fts_available() -> bool:
    return bool(_fts_available)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)
        conn.commit()
