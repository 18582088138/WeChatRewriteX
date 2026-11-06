"""Additive audio extension schema, independently versioned from team schema."""
import json
import sqlite3
import time
from pathlib import Path
from . import db


def migrate():
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='audio_schema'").fetchone():
            version = conn.execute('SELECT MAX(version) FROM audio_schema').fetchone()[0]
            if version != 1:
                raise RuntimeError('音频数据库来自不兼容版本，请使用匹配程序或完整备份恢复')
            return
        if conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
            backup = db.db_path().parent / 'backups' / 'before-audio-v1.sqlite3'
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                target = sqlite3.connect(backup)
                try:
                    conn.backup(target)
                finally:
                    target.close()
        ddl = Path(__file__).with_name('audio_schema.sql').read_text(encoding='utf-8')
        conn.executescript('BEGIN IMMEDIATE;' + ddl + f'INSERT INTO audio_schema VALUES(1,{time.time()}); COMMIT;')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def setting(key, default=None):
    row = db.query_one('SELECT value_json FROM audio_settings WHERE key=?', (key,))
    return json.loads(row['value_json']) if row else default


def set_setting(key, value):
    db.execute('INSERT INTO audio_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', (key, dumps(value)))
