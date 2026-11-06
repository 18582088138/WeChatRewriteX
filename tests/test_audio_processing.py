"""S7 processing upgrades reuse TTS while invalidating complete output batches."""
import json
import pytest
from tests.test_audio import speech, synth
from app.services import audio, audio_processing as processing, tts
from app.services.audio_models import Generate
from app.storage import db


def test_upgraded_processing_rebuilds_complete_output_without_new_tts(speech):
    aid, state = speech
    first = synth(aid, state)
    legacy = dict(first['snapshot'])
    legacy.pop('processing_version')
    db.execute('UPDATE audio_batches SET snapshot_json=?,input_hash=? WHERE id=?',
               (json.dumps(legacy), audio.input_hash(legacy), first['id']))
    assert audio.batch(aid, first['id'])['stale']
    pending = audio.generate(aid, Generate(revision=state['product']['revision']))
    assert pending['id'] != first['id']
    assert pending['attempts'] == []
    assert audio.run_batch(aid, {'batch_id': pending['id']})['status'] == 'done'
    rebuilt = audio.batch(aid, pending['id'])
    assert rebuilt['result']['cache_hits'] == 2
    assert rebuilt['result']['loudness']['method'].startswith('ffmpeg loudnorm two-pass')
    assert processing.probe(audio.file_path(aid, first['files'][0]['id'])) > 0


def test_disguised_playlist_cannot_read_a_referenced_audio_file(tmp_path):
    reference = tmp_path/'reference.wav'
    reference.write_bytes(tts.FakeTTS().synthesize('已登记的本地测试音', {}, None, 'zh').audio)
    playlist = tmp_path/'disguised.wav'
    playlist.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:1,\n'+reference.as_uri()+'\n#EXT-X-ENDLIST\n')
    assert processing.probe(reference) > 0
    with pytest.raises(ValueError, match='处理失败'):
        processing.probe(playlist)
