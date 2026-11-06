"""S2 derives and edits speech without importing or calling a TTS provider."""
from types import SimpleNamespace
import pytest
from app.core.models import DraftDoc, Block
from app.storage import dao
from app.services import audio
from app.services.audio_models import Derive, SpeechDoc, Rewrite
from app.services.draft_service import VersionConflict


@pytest.fixture
def article():
    aid = dao.create_article('', '口播事实')['id']
    doc = DraftDoc(id=aid+'-v1', article_id=aid, version=1, blocks=[
        Block(id='one', type='paragraph', text='2026年11月6日，性能提高12.5%。[1]'),
        Block(id='two', type='paragraph', text='AI 内存为32GB，型号GPT-4。')])
    dao.save_workspace(doc, 'test')
    return aid


def test_derive_pronunciation_reorder_and_manual_reading_are_independent(article):
    before = dao.latest_draft(article)['doc_json']
    state = audio.derive(article, Derive())
    doc = SpeechDoc.model_validate(state['product']['doc'])
    assert '百分之十二点五' in doc.paragraphs[0].speech_text
    assert '[1]' not in doc.paragraphs[0].speech_text
    assert '三十二吉字节' in doc.paragraphs[1].speech_text
    ids = [p.id for p in doc.paragraphs]
    doc.paragraphs.reverse()
    doc.paragraphs[0].manual_speech = True
    doc.paragraphs[0].speech_text = '人工指定读法。'
    changed = audio.save(article, state['product']['revision'], doc)
    assert [p['id'] for p in changed['product']['doc']['paragraphs']] == ids[::-1]
    assert changed['product']['doc']['paragraphs'][0]['speech_text'] == '人工指定读法。'
    assert dao.latest_draft(article)['doc_json'] == before


def test_ai_derive_changed_numbers_is_rejected_without_partial_save(article, monkeypatch):
    from app.services.llm import router
    def wrong(*args, **kwargs):
        import json
        paragraphs = json.loads(args[1][1]['content'])['paragraphs']
        paragraphs[0]['text'] = '性能提高99%。'
        return SimpleNamespace(parsed=kwargs['schema'](paragraphs=paragraphs))
    monkeypatch.setattr(router, 'complete', wrong)
    with pytest.raises(ValueError, match='数字'):
        audio.derive(article, Derive(use_llm=True))
    assert audio.get(article)['product'] is None


def test_late_local_rewrite_preserves_new_manual_revision(article, monkeypatch):
    from app.services.llm import router
    state = audio.derive(article, Derive())
    doc = SpeechDoc.model_validate(state['product']['doc'])
    pid = doc.paragraphs[0].id
    def late(*args, **kwargs):
        doc.paragraphs[0].text += '人工最新内容。'
        audio.save(article, state['product']['revision'], doc)
        return SimpleNamespace(parsed=kwargs['schema'](text=doc.paragraphs[0].text))
    monkeypatch.setattr(router, 'complete', late)
    with pytest.raises(VersionConflict):
        audio.rewrite(article, Rewrite(revision=1, paragraph_id=pid, instruction='保留事实'))
    assert '人工最新内容' in audio.get(article)['product']['doc']['paragraphs'][0]['text']
