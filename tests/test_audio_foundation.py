"""S1 storage snapshots and migration boundaries, independent of TTS/derivation."""
import sqlite3
import pytest
from app.storage import db, dao, audio_store
from app.services import audio
from app.services.audio_models import SpeechDoc, Paragraph
from app.services.draft_service import VersionConflict
from app.core.models import DraftDoc, Block


def test_first_save_binds_source_and_history_survives_restart():
    aid = dao.create_article('', 'S1独立产物')['id']
    source = DraftDoc(id=aid+'-v1', article_id=aid, version=1,
                      blocks=[Block(id='source', type='paragraph', text='图文原始事实。')])
    dao.save_workspace(source, 'test')
    article_before = dao.latest_draft(aid)['doc_json']
    speech = SpeechDoc(source_hash='forged', source_confirmed_hash='forged', rules_version='forged',
                       paragraphs=[Paragraph(id='stable', text='口播事实。', speech_text='')])
    first = audio.save(aid, 0, speech)
    saved = first['product']['doc']
    assert saved['source_hash'] == audio.source(aid)[1]
    assert saved['source_confirmed_hash'] == ''
    assert saved['rules_version'] == 'speech-rules-1'
    speech = SpeechDoc.model_validate(saved)
    speech.paragraphs[0].text = '人工口播修改。'
    second = audio.save(aid, 1, speech)
    with pytest.raises(VersionConflict):
        audio.save(aid, 1, speech)
    db.init_db()
    assert audio.get(aid)['product']['revision'] == 2
    assert [v['revision'] for v in audio.history(aid)] == [2, 1]
    assert second['product']['doc']['paragraphs'][0]['id'] == 'stable'
    assert dao.latest_draft(aid)['doc_json'] == article_before
    source.blocks[0].text = '来源后来变化。'
    source.edit_revision += 1
    dao.save_workspace(source, 'test')
    assert audio.get(aid)['product']['source_stale']
    assert not audio.confirm_source(aid, 2)['product']['source_stale']


def _old_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(db._SCHEMA)
    dao.create_article('', '旧数据库项目')


def test_additive_migration_backups_existing_database_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('WENSHU_DATA_DIR', str(tmp_path))
    _old_database(db.db_path())
    db.init_db()
    assert db.query_one('SELECT version FROM audio_schema')['version'] == 1
    assert (tmp_path/'backups/before-audio-v1.sqlite3').is_file()
    assert db.query_one('PRAGMA user_version')['user_version'] == 3
    db.init_db()
    assert len(db.query('SELECT * FROM audio_schema')) == 1
    with sqlite3.connect(tmp_path/'backups/before-audio-v1.sqlite3') as backup:
        assert backup.execute('SELECT COUNT(*) FROM articles').fetchone()[0] == 1
        assert not backup.execute("SELECT name FROM sqlite_master WHERE name='audio_schema'").fetchone()


def test_failed_extension_migration_is_atomic(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setenv('WENSHU_DATA_DIR', str(tmp_path))
    _old_database(db.db_path())
    original = Path.read_text
    def corrupt(path, *args, **kwargs):
        if path.name == 'audio_schema.sql':
            return 'CREATE TABLE audio_schema(version INTEGER); THIS IS INVALID;'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', corrupt)
    with pytest.raises(sqlite3.OperationalError):
        audio_store.migrate()
    assert db.query_one("SELECT name FROM sqlite_master WHERE name='audio_schema'") is None
    assert db.query_one('SELECT COUNT(*) AS n FROM articles')['n'] == 1
