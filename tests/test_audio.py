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


def test_incremental_cache_reorder_mix_and_valid_mp3(speech):
    aid,data=speech
    first=synth(aid,data)
    assert len(first['attempts'])==2
    assert first['result']['duration']>0
    assert first['result']['loudness']['method'].startswith('ffmpeg')
    assert not first['result']['precise_word_alignment']
    again=audio.generate(aid,Generate(revision=data['product']['revision']))
    assert again['id']==first['id']
    doc=SpeechDoc.model_validate(data['product']['doc'])
    doc.paragraphs[0].text+='补充一句。'
    changed=audio.save(aid,data['product']['revision'],doc)
    second=synth(aid,changed)
    assert len(second['attempts'])==1
    assert second['result']['cache_hits']==1
    assert audio.batch(aid,first['id'])['stale']
    doc=SpeechDoc.model_validate(changed['product']['doc']);doc.paragraphs.reverse()
    reordered=audio.save(aid,changed['product']['revision'],doc)
    third=synth(aid,reordered)
    assert third['attempts']==[]
    assert third['result']['timeline'][0]['paragraph_id']==doc.paragraphs[0].id
    assert third['result']['timeline'][1]['start']>third['result']['timeline'][0]['end']
    doc.mix.loudness_lufs=-18
    mixed=audio.save(aid,reordered['product']['revision'],doc)
    fourth=synth(aid,mixed)
    assert fourth['attempts']==[]
    audio.file_path(aid,first['files'][0]['id']) # old versions stay readable


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


def test_pronunciation_dictionary_changes_only_used_segments(speech):
    aid,data=speech
    synth(aid,data)
    doc=SpeechDoc.model_validate(data['product']['doc']);doc.dictionary={'AI':'人工智能'}
    updated=audio.save(aid,data['product']['revision'],doc)
    changed=synth(aid,updated)
    assert len(changed['attempts'])==1
    assert changed['result']['cache_hits']==1


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


def test_subtitle_correction_creates_new_candidate_without_calls(speech):
    from app.services.audio_models import Subtitles
    aid,data=speech
    b=synth(aid,data)
    cues=[{k:c[k] for k in ('paragraph_id','start','end','text')} for c in b['result']['timeline']]
    cues[0]['text']='修正字幕显示'
    corrected=audio.update_subtitles(aid,b['id'],Subtitles(cues=cues))
    assert corrected['id']!=b['id']
    assert corrected['attempts']==[]
    assert audio.batch(aid,b['id'])['result']['timeline'][0]['text']!=cues[0]['text']
    assert corrected['result']['timeline'][0]['quality']=='manual_paragraph'
    assert audio.get(aid)['product']['doc']==data['product']['doc']
    cues[1]['start']=0
    with pytest.raises(ValueError,match='有序'):
        audio.update_subtitles(aid,b['id'],Subtitles(cues=cues))


def test_mix_intro_music_outro_uses_local_media_and_cache(speech):
    from app.storage import library
    from app.services import audio_processing
    aid,data=speech
    first=synth(aid,data)
    target=library.article_dir(aid)/'music.wav'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(tts.FakeTTS().synthesize('离线音乐素材',{},None,'zh').audio)
    from app.core.ids import new_id
    mid=new_id('material')
    db.execute('INSERT INTO materials(id,scope,article_id,kind,path,title,sha256) VALUES(?,?,?,?,?,?,?)',
               (mid,'article',aid,'audio',str(target.relative_to(library.library_root())),'离线音乐',audio_processing.checksum(target)))
    doc=SpeechDoc.model_validate(data['product']['doc'])
    doc.mix.music_id=mid;doc.mix.intro_id=mid;doc.mix.outro_id=mid;doc.mix.license_note='自建离线测试音，允许测试使用'
    doc.mix.trim_seconds=.5
    updated=audio.save(aid,data['product']['revision'],doc)
    mixed=synth(aid,updated)
    assert mixed['attempts']==[]
    assert mixed['result']['timeline'][0]['start']>=.5
    assert mixed['result']['duration']>first['result']['duration']
    assert float(mixed['result']['loudness']['measured']['input_tp'])<0


def test_processing_failure_and_low_disk_keep_export(speech,monkeypatch):
    aid,data=speech
    script=audio.submit_review(aid,SubmitReview(kind='script',revision=data['product']['revision']))
    audio.decide_review(aid,script['id'],ReviewAction(status='approved'))
    first=synth(aid,data)
    review=audio.submit_review(aid,SubmitReview(kind='audio',revision=data['product']['revision'],batch_id=first['id']))
    audio.decide_review(aid,review['id'],ReviewAction(status='approved'))
    audio.export(aid,first['id'])
    # Publishing the same approved package remains idempotent after manifest files were added.
    audio.export(aid,first['id'])
    doc=SpeechDoc.model_validate(data['product']['doc']);doc.mix.loudness_lufs=-18
    updated=audio.save(aid,data['product']['revision'],doc)
    new=audio.generate(aid,Generate(revision=updated['product']['revision']))
    def fail(*args):raise ValueError('模拟本地合并失败')
    monkeypatch.setattr(audio.processing,'compose',fail)
    assert audio.run_batch(aid,{'batch_id':new['id']})['status']=='failed'
    assert db.query_one('SELECT batch_id FROM audio_exports WHERE article_id=?',(aid,))['batch_id']==first['id']
    import shutil
    usage=shutil.disk_usage(audio.root())
    monkeypatch.setattr(audio.shutil,'disk_usage',lambda *args:type(usage)(usage.total,usage.used,0))
    with pytest.raises(ValueError,match='256MB'):
        audio.generate(aid,Generate(revision=updated['product']['revision']))


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
