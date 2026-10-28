"""SQLite 连接与初始化。同步 sqlite3 + FastAPI 同步路由(threadpool)，本地单用户足够。"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from ..core.config import data_dir

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
_db_path: Path | None = None
_fts_available: bool | None = None
_local = threading.local()


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = data_dir() / "app.db"
    return _db_path


@contextmanager
def connect():
    """Close every owned connection; DAO calls share the current unit of work."""
    active = getattr(_local, "connection", None)
    if active is not None:
        yield active
        return
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """Serialize short read/modify/write operations, with nested savepoints."""
    active = getattr(_local, "connection", None)
    if active is not None:
        depth = getattr(_local, "depth", 0) + 1
        _local.depth = depth
        name = f"uow_{depth}"
        active.execute(f"SAVEPOINT {name}")
        callbacks = len(_local.callbacks)
        try:
            yield active
            active.execute(f"RELEASE SAVEPOINT {name}")
        except BaseException:
            active.execute(f"ROLLBACK TO SAVEPOINT {name}")
            active.execute(f"RELEASE SAVEPOINT {name}")
            del _local.callbacks[callbacks:]
            raise
        finally:
            _local.depth -= 1
        return
    callbacks = []
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _local.connection, _local.callbacks, _local.depth = conn, callbacks, 0
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            _local.connection = None
            _local.callbacks = []
    for callback in callbacks:
        callback()


def after_commit(callback) -> None:
    """Run notifications/file projections only after the authoritative DB commits."""
    if getattr(_local, "connection", None) is not None:
        _local.callbacks.append(callback)
    else:
        callback()


def init_db() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(_SCHEMA)
        # 轻量迁移：老库补 lib_dir 列 + sha256 唯一索引降级为普通索引
        for ddl in ("ALTER TABLE articles ADD COLUMN lib_dir TEXT",
                    "ALTER TABLE articles ADD COLUMN selected_json TEXT DEFAULT '[]'",
                    "ALTER TABLE drafts ADD COLUMN note TEXT DEFAULT ''",
                    "ALTER TABLE materials ADD COLUMN deleted_at TEXT",
                    "ALTER TABLE embeddings ADD COLUMN model_id TEXT",
                    "ALTER TABLE embeddings ADD COLUMN content_hash TEXT"):
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


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn:
        return conn.execute(sql, params).rowcount
