"""S8 manual caption candidates retain audio and require their own approval."""
import json
import zipfile
import pytest
from tests.test_audio import speech, synth
from app.services import audio
from app.services.audio_models import Subtitles, SubmitReview, ReviewAction
from app.storage import db


def _cues(batch):
    return [{key: cue[key] for key in ('paragraph_id', 'start', 'end', 'text')} for cue in batch['result']['timeline']]


def test_corrected_caption_candidate_is_approvable_and_exportable(speech):
    aid, state = speech
    first = synth(aid, state)
    original = next(f for f in first['files'] if f['name'] == 'audio.mp3')
    checksum = audio.processing.checksum(audio.file_path(aid, original['id']))
    review = audio.submit_review(aid, SubmitReview(kind='script', revision=state['product']['revision']))
    audio.decide_review(aid, review['id'], ReviewAction(status='approved'))
    cues = _cues(first)
    cues[0]['text'] = '人工修正后的字幕'
    corrected = audio.update_subtitles(aid, first['id'], Subtitles(cues=cues))
    assert corrected['attempts'] == [] and not corrected['stale']
    review = audio.submit_review(aid, SubmitReview(kind='audio', revision=state['product']['revision'], batch_id=corrected['id']))
    audio.decide_review(aid, review['id'], ReviewAction(status='approved'))
    exported = audio.export(aid, corrected['id'])
    package = audio.file_path(aid, exported['package_url'].split('/')[-1])
    with zipfile.ZipFile(package) as archive:
        assert '人工修正后的字幕' in archive.read('subtitles.srt').decode()
        assert archive.read('subtitles.vtt').startswith(b'WEBVTT')
    assert audio.processing.checksum(audio.file_path(aid, original['id'])) == checksum
    assert db.query_one('SELECT batch_id FROM audio_exports WHERE article_id=?', (aid,))['batch_id'] == corrected['id']


def test_outdated_processing_batch_cannot_create_a_current_caption_candidate(speech):
    aid, state = speech
    first = synth(aid, state)
    snapshot = dict(first['snapshot'], processing_version='audio-mix-v1')
    db.execute('UPDATE audio_batches SET snapshot_json=?,input_hash=? WHERE id=?',
               (json.dumps(snapshot), audio.input_hash(snapshot), first['id']))
    with pytest.raises(ValueError, match='最新'):
        audio.update_subtitles(aid, first['id'], Subtitles(cues=_cues(first)))
