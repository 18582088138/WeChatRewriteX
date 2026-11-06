"""S4 cached incremental synthesis and transactional shared request reservations."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from tests.test_audio import speech, synth
from app.services import audio
from app.services.audio_models import SpeechDoc, Generate, VoiceProfile, Limits


def test_incremental_edit_and_reordering_reuse_segments(speech):
    aid, state = speech
    first = synth(aid, state)
    assert len(first['attempts']) == 2
    doc = SpeechDoc.model_validate(state['product']['doc'])
    doc.paragraphs[0].text += '只改这一段。'
    changed = audio.save(aid, state['product']['revision'], doc)
    second = synth(aid, changed)
    assert len(second['attempts']) == 1
    assert second['result']['cache_hits'] == 1
    doc.paragraphs.reverse()
    reordered = audio.save(aid, changed['product']['revision'], doc)
    third = synth(aid, reordered)
    assert third['attempts'] == []
    assert [p['paragraph_id'] for p in third['result']['segment_manifest']] == [p.id for p in doc.paragraphs]
    assert first['files'] and audio.file_path(aid, first['files'][0]['id']).is_file()


def test_parallel_batches_cannot_reserve_above_shared_budget(speech, monkeypatch):
    aid, state = speech
    profile = audio.register_profile(VoiceProfile(voice_id='known', name='已有声音', authorization='只测试预留', projects=[aid]))
    doc = SpeechDoc.model_validate(state['product']['doc'])
    doc.voice.profile_id = profile['id']
    saved = audio.save(aid, state['product']['revision'], doc)
    monkeypatch.setenv('MINIMAX_TTS_API_KEY', 'isolated-test-key')
    audio.set_limits(Limits(max_requests=2, max_chars=120))
    def reserve():
        return audio.generate(aid, Generate(revision=saved['product']['revision']))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results[0]['id'] == results[1]['id']
    assert audio.billing(aid)['reserved_requests'] == 2
    assert audio.billing(aid)['sent_requests'] == 0
    doc.voice.speed = 1.1
    changed = audio.save(aid, saved['product']['revision'], doc)
    with pytest.raises(Exception, match='额度不足'):
        audio.generate(aid, Generate(revision=changed['product']['revision']))
    audio.cancel(aid, results[0]['id'])
    audio.set_limits(Limits())
