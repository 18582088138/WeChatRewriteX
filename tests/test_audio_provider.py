"""S3 existing voice scope, explicit inventory caching and valid MP3 responses."""
from contextlib import contextmanager
import json
import pytest
from app.services import audio, tts, audio_processing as processing
from app.services.audio_models import SpeechDoc, VoiceProfile, VoiceSettings
from app.storage import dao, audio_store


def test_voice_scope_and_disabling_never_falls_back(monkeypatch):
    monkeypatch.setenv('WENSHU_FAKE_TTS', '1')
    first = dao.create_article('', '已授权')['id']
    other = dao.create_article('', '未授权')['id']
    profile = audio.register_profile(VoiceProfile(provider='fake', voice_id='known', name='已有声音',
                                      authorization='固定测试音', projects=[first]))
    doc = SpeechDoc(voice=VoiceSettings(profile_id=profile['id']))
    assert audio.voice_for(first, doc)['voice_id'] == 'known'
    with pytest.raises(ValueError, match='获准'):
        audio.voice_for(other, doc)
    audio.register_profile(VoiceProfile(provider='fake', voice_id='known', name='已有声音',
                           authorization='固定测试音', projects=[first], enabled=False), profile['id'])
    with pytest.raises(ValueError, match='获准'):
        audio.voice_for(first, doc)


def test_inventory_failure_is_cached_and_not_retried(monkeypatch):
    audio_store.set_setting('inventory', None)
    calls = []
    def fail():
        calls.append(1)
        raise tts.TTSError('模拟不可用')
    monkeypatch.setattr(tts, 'inventory', fail)
    first = audio.query_inventory()
    assert first['state'] == 'unconfirmed'
    assert audio.query_inventory() == first
    assert calls == [1]
    audio_store.set_setting('inventory', None)


def test_hex_mp3_response_decodes_completely_without_real_network(tmp_path, monkeypatch):
    wav = tmp_path/'fixed.wav'
    mp3 = tmp_path/'fixed.mp3'
    wav.write_bytes(tts.FakeTTS().synthesize('固定音频契约', {}, None, 'zh').audio)
    processing.run('ffmpeg', ['-v', 'error', '-y', *processing.input_args(wav), '-c:a', 'libmp3lame', str(mp3)])
    captured = []
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_bytes(self):
            yield json.dumps({'base_resp': {'status_code': 0}, 'data': {'audio': mp3.read_bytes().hex()},
                              'extra_info': {'usage_characters': 12}, 'trace_id': 'offline-trace'}).encode()
    class Client:
        def stream(self, method, url, headers, json):
            captured.append((method, url, json))
            return Response()
    @contextmanager
    def client(*args, **kwargs): yield Client()
    monkeypatch.setattr(tts, 'client_for', client)
    monkeypatch.setenv('MINIMAX_TTS_API_KEY', 'isolated-test-key')
    result = tts.MiniMaxTTS().synthesize('固定音频契约', {'voice_id': 'existing-id'}, VoiceSettings(), 'zh')
    received = tmp_path/'received.mp3'
    received.write_bytes(result.audio)
    assert processing.probe(received) > 0
    assert result.usage_characters == 12
    assert captured[0][1].endswith('/v1/t2a_v2')
    assert captured[0][2]['voice_setting']['voice_id'] == 'existing-id'
