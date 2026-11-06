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


def test_queued_cancel_and_unknown_never_auto_resends(speech,monkeypatch):
    aid,data=speech
    pending=audio.generate(aid,Generate(revision=data['product']['revision']))
    cancelled=audio.cancel(aid,pending['id'])
    assert cancelled['status']=='cancelled'
    assert all(a['sent_at'] is None for a in cancelled['attempts'])
    assert audio.run_batch(aid,{'batch_id':pending['id']})['status']=='cancelled'
    def unknown(*args):
        raise tts.TTSError('响应未知','unknown')
    monkeypatch.setattr(tts.FakeTTS,'synthesize',unknown)
    retry=audio.generate(aid,Generate(revision=data['product']['revision']))
    assert audio.run_batch(aid,{'batch_id':retry['id']})['status']=='unknown'
    audio.recover()
    with pytest.raises(Exception,match='响应未知'):
        audio.generate(aid,Generate(revision=data['product']['revision']))
    assert sum(a['state']=='unknown' for a in audio.batch(aid,retry['id'])['attempts'])==1
    assert sum(a['state']=='reserved' for a in audio.batch(aid,retry['id'])['attempts'])==0


def test_billing_reserves_shared_limits_and_no_network(speech,monkeypatch):
    aid,data=speech
    profile=audio.register_profile(VoiceProfile(voice_id='known',name='已知',authorization='用户授权',projects=[aid]))
    doc=SpeechDoc.model_validate(data['product']['doc']);doc.voice.profile_id=profile['id']
    updated=audio.save(aid,data['product']['revision'],doc)
    monkeypatch.setenv('MINIMAX_TTS_API_KEY','test-sentinel')
    audio.set_limits(Limits(max_requests=1,max_chars=120))
    with pytest.raises(Exception,match='额度不足'):
        audio.generate(aid,Generate(revision=updated['product']['revision']))
    audio.set_limits(Limits(max_requests=2,max_chars=120))
    batch=audio.generate(aid,Generate(revision=updated['product']['revision']))
    ledger=audio.billing(aid)
    assert ledger['reserved_requests']==2
    assert ledger['sent_requests']==0
    assert ledger['estimated_cost'] is None
    audio.cancel(aid,batch['id'])
    assert audio.billing(aid)['committed_requests']==0
    audio.set_limits(Limits())


def test_human_script_audio_approval_export_and_change(speech):
    aid,data=speech
    script=audio.submit_review(aid,SubmitReview(kind='script',revision=data['product']['revision']))
    audio.decide_review(aid,script['id'],ReviewAction(status='approved'))
    finished=synth(aid,data)
    with pytest.raises(Exception,match='人工批准'):
        audio.export(aid,finished['id'])
    review=audio.submit_review(aid,SubmitReview(kind='audio',revision=data['product']['revision'],batch_id=finished['id']))
    audio.decide_review(aid,review['id'],ReviewAction(status='approved'))
    exported=audio.export(aid,finished['id'])
    assert exported['approval_id']==review['id']
    assert 'API_KEY' not in json.dumps(exported)
    doc=SpeechDoc.model_validate(data['product']['doc']);doc.voice.speed=1.1
    audio.save(aid,data['product']['revision'],doc)
    assert any(r['status']=='approved' and r['kind']=='script' for r in audio.reviews(aid))
    with pytest.raises(Exception,match='最新'):
        audio.export(aid,finished['id'])
    assert db.query_one('SELECT batch_id FROM audio_exports WHERE article_id=?',(aid,))['batch_id']==finished['id']


def test_source_change_requires_manual_recheck(speech):
    aid,data=speech
    old=DraftDoc.model_validate_json(dao.latest_draft(aid)['doc_json'])
    old.blocks[0].text='来源改变。';old.edit_revision+=1
    dao.save_workspace(old,'test')
    assert audio.get(aid)['product']['source_stale']
    with pytest.raises(Exception,match='来源已改变'):
        audio.submit_review(aid,SubmitReview(kind='script',revision=data['product']['revision']))
    reviewed=audio.confirm_source(aid,data['product']['revision'])
    assert not reviewed['product']['source_stale']


def test_adapter_hex_errors_and_endpoint_whitelist(monkeypatch):
    monkeypatch.setenv('MINIMAX_TTS_ORIGIN','https://evil.invalid/v1/voice_clone')
    with pytest.raises(tts.TTSError,match='官方'):
        tts.origin()
    result=tts.FakeTTS().synthesize('测试',{},None,'zh')
    assert result.audio.startswith(b'RIFF')
    assert result.audio==tts.FakeTTS().synthesize('测试',{},None,'zh').audio


def test_restart_sent_request_unknown_and_queued_reservations(speech):
    aid,data=speech
    b=audio.generate(aid,Generate(revision=data['product']['revision']))
    db.execute("UPDATE audio_batches SET status='running' WHERE id=?",(b['id'],))
    db.execute("UPDATE audio_attempts SET state='sent',sent_at=123 WHERE id=?",(b['attempts'][0]['id'],))
    audio.recover()
    recovered=audio.batch(aid,b['id'])
    assert recovered['status']=='unknown'
    assert recovered['attempts'][0]['state']=='unknown'
    assert recovered['attempts'][1]['state']=='cancelled_unissued'


def test_billing_han_double_units_and_model_rate(speech):
    aid,data=speech
    assert audio.billable_chars('中文 AI!')==8
    audio.set_limits(Limits(rate_per_10k=3.5,rate_source='official China pricing',rate_effective='2026-11-05'))
    estimate=audio.estimate(aid)
    assert estimate['billable_chars']>estimate['chars']
    assert estimate['estimated_cost']==estimate['billable_chars']*3.5/10000
    doc=SpeechDoc.model_validate(data['product']['doc']);doc.voice.model='speech-2.6-turbo'
    audio.save(aid,data['product']['revision'],doc)
    assert audio.estimate(aid)['estimated_cost'] is None # HD rate never silently applies to Turbo.
    audio.set_limits(Limits())


def test_corrupt_cache_cannot_be_reused(speech):
    aid,data=speech
    first=synth(aid,data)
    segments=audio.get(aid)['segments']
    record=db.query_one('SELECT * FROM audio_segments WHERE id=?',(segments[0]['url'].split('/')[-1],))
    (audio.root()/record['path']).write_bytes(b'broken')
    assert audio.get(aid)['segments'][0]['stale']
    assert audio.estimate(aid)['new_requests']==1
    from app.services.audio_models import Generate
    second=audio.generate(aid,Generate(revision=data['product']['revision'],paragraph_ids=[data['product']['doc']['paragraphs'][0]['id']]))
    assert len(second['attempts'])==1


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


def test_sent_cancellation_preserves_attempt_and_blocks_later_requests(speech,monkeypatch):
    aid,data=speech
    b=audio.generate(aid,Generate(revision=data['product']['revision']))
    original=tts.FakeTTS.synthesize
    calls=[]
    def synthesize(self,*args):
        calls.append(1)
        audio.cancel(aid,b['id'])
        return original(self,*args)
    monkeypatch.setattr(tts.FakeTTS,'synthesize',synthesize)
    assert audio.run_batch(aid,{'batch_id':b['id']})['status']=='cancelled'
    result=audio.batch(aid,b['id'])
    assert len(calls)==1
    assert result['attempts'][0]['sent_at'] is not None
    assert result['attempts'][1]['sent_at'] is None
    assert result['files']==[]


def test_ai_review_cannot_overwrite_new_script(speech,monkeypatch):
    from app.services.llm import router
    aid,data=speech
    def late(*args,**kwargs):
        from types import SimpleNamespace
        doc=SpeechDoc.model_validate(data['product']['doc']);doc.paragraphs[0].text+='人工已修改。'
        audio.save(aid,data['product']['revision'],doc)
        return SimpleNamespace(parsed=kwargs['schema'](issues=[]),model='fixture')
    monkeypatch.setattr(router,'complete',late)
    with pytest.raises(draft_conflict()):
        audio.ai_review(aid,data['product']['revision'])
    assert audio.get(aid)['ai_review'] is None
    assert '人工已修改' in audio.get(aid)['product']['doc']['paragraphs'][0]['text']


def test_cannot_forge_source_position(speech):
    aid,data=speech
    doc=SpeechDoc.model_validate(data['product']['doc'])
    doc.paragraphs[0].source_block_ids=['invented-other-project-position']
    with pytest.raises(ValueError,match='来源位置'):
        audio.save(aid,data['product']['revision'],doc)
