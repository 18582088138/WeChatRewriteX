"""Audio tests never use developer credentials or paid network requests."""
import json
import pytest
from app.services import audio, tts
from app.services.audio_models import Derive, Generate, VoiceProfile, SpeechDoc, Limits, SubmitReview, ReviewAction
from app.storage import db, dao
from app.core.models import DraftDoc, Block


@pytest.fixture
def speech(monkeypatch):
    monkeypatch.setenv('WENSHU_FAKE_TTS', '1')
    article = dao.create_article('', '科技新闻')
    aid = article['id']
    doc = DraftDoc(id=aid+'-v1', article_id=aid, version=1, blocks=[
        Block(id='b1',type='paragraph',text='2026年11月5日，模型速度提高12.5%。[1]'),
        Block(id='b2',type='paragraph',text='AI 芯片内存为32GB，型号GPT-4。')])
    dao.save_workspace(doc,'test')
    data = audio.derive(aid,Derive())
    profile = audio.register_profile(VoiceProfile(provider='fake',voice_id='fixture',name='离线测试',authorization='仅离线测试',projects=[aid]))
    draft = SpeechDoc.model_validate(data['product']['doc'])
    draft.voice.profile_id = profile['id']
    data = audio.save(aid,data['product']['revision'],draft)
    return aid, data


def synth(aid, data, selected=None):
    batch = audio.generate(aid,Generate(revision=data['product']['revision'],paragraph_ids=selected))
    audio.run_batch(aid,{'batch_id':batch['id']})
    result = audio.batch(aid,batch['id'])
    assert result['status']=='done',result
    return result


def test_independent_draft_history_and_pronunciation(speech):
    aid,data=speech
    current=dao.latest_draft(aid)['doc_json']
    doc=SpeechDoc.model_validate(data['product']['doc'])
    assert '百分之十二点五' in doc.paragraphs[0].speech_text
    assert '[1]' not in doc.paragraphs[0].speech_text
    assert '三十二吉字节' in doc.paragraphs[1].speech_text
    ids=[p.id for p in doc.paragraphs]
    doc.paragraphs[0].text='人工口播修订。'
    saved=audio.save(aid,data['product']['revision'],doc)
    assert dao.latest_draft(aid)['doc_json']==current
    assert [p['id'] for p in saved['product']['doc']['paragraphs']]==ids
    assert len(audio.history(aid))==3
    with pytest.raises(draft_conflict()):
        audio.save(aid,data['product']['revision'],doc)
    db.init_db()
    assert audio.get(aid)['product']['revision']==saved['product']['revision']


def draft_conflict():
    from app.services.draft_service import VersionConflict
    return VersionConflict


def test_adapter_hex_errors_and_endpoint_whitelist(monkeypatch):
    monkeypatch.setenv('MINIMAX_TTS_ORIGIN','https://evil.invalid/v1/voice_clone')
    with pytest.raises(tts.TTSError,match='官方'):
        tts.origin()
    result=tts.FakeTTS().synthesize('测试',{},None,'zh')
    assert result.audio.startswith(b'RIFF')
    assert result.audio==tts.FakeTTS().synthesize('测试',{},None,'zh').audio


def test_minimax_adapter_response_contract_and_no_clone_paths(monkeypatch):
    from contextlib import contextmanager
    sent=[]
    fixture=tts.FakeTTS().synthesize('测试',{},None,'zh').audio
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_bytes(self):
            yield json.dumps({'base_resp':{'status_code':0},'data':{'audio':fixture.hex()},'trace_id':'safe-trace','extra_info':{'usage_characters':4}}).encode()
    class Client:
        def stream(self,method,url,headers,json):
            sent.append((method,url,json));return Response()
    @contextmanager
    def fake(*args,**kwargs):yield Client()
    monkeypatch.setenv('MINIMAX_TTS_API_KEY','test-sentinel')
    monkeypatch.setattr(tts,'client_for',fake)
    result=tts.MiniMaxTTS().synthesize('测试',{'voice_id':'existing'},audio.VoiceSettings(),'zh')
    assert result.usage_characters==4
    assert result.audio==fixture
    assert sent[0][1].endswith('/v1/t2a_v2')
    assert sent[0][2]['voice_setting']['voice_id']=='existing'
    assert 'test-sentinel' not in json.dumps(sent)


def test_cannot_forge_source_position(speech):
    aid,data=speech
    doc=SpeechDoc.model_validate(data['product']['doc'])
    doc.paragraphs[0].source_block_ids=['invented-other-project-position']
    with pytest.raises(ValueError,match='来源位置'):
        audio.save(aid,data['product']['revision'],doc)
