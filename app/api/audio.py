"""Audio endpoints stay under the current project authorization boundary."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field
from ..services import audio, tts
from ..services.audio_models import (SaveSpeech, Derive, Rewrite, VoiceProfile, Limits, Generate,
                                    SubmitReview, ReviewAction, Subtitles, Strict)

router = APIRouter(tags=['音频创作'])
BASE = '/api/articles/{aid}/audio'


@router.get(BASE)
def get(aid: str):
    return audio.get(aid)


@router.put(BASE + '/speech')
def save(aid: str, request: SaveSpeech):
    return audio.save(aid, request.revision, request.doc)


@router.post(BASE + '/derive')
def derive(aid: str, request: Derive):
    return audio.derive(aid, request)


@router.post(BASE + '/rewrite')
def rewrite(aid: str, request: Rewrite):
    return audio.rewrite(aid, request)


@router.get(BASE + '/history')
def history(aid: str):
    return {'versions': audio.history(aid)}


class Revision(Strict):
    revision: int = Field(ge=1)


@router.post(BASE + '/confirm-source')
def confirm(aid: str, request: Revision):
    return audio.confirm_source(aid, request.revision)


@router.get(BASE + '/estimate')
def estimate(aid: str):
    return audio.estimate(aid)


@router.post(BASE + '/generate')
def generate(aid: str, request: Generate):
    return audio.generate(aid, request)


@router.get(BASE + '/batches/{bid}')
def batch(aid: str, bid: str):
    return audio.batch(aid, bid)


@router.post(BASE + '/batches/{bid}/cancel')
def cancel(aid: str, bid: str):
    return audio.cancel(aid, bid)


@router.get(BASE + '/files/{oid}')
def file(aid: str, oid: str):
    path = audio.file_path(aid, oid)
    return FileResponse(path, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get(BASE + '/segments/{oid}')
def segment(aid: str, oid: str):
    path = audio.file_path(aid, oid, True)
    return FileResponse(path, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/api/audio/settings')
def settings():
    from ..storage import audio_store
    return {'limits': audio.limits().model_dump(), 'voices': audio.profiles(),
            'default_voice_id': audio.config.get_env('MINIMAX_DEFAULT_VOICE_ID') or '',
            'key_set': bool(audio.config.get_env('MINIMAX_TTS_API_KEY')), 'ledger': audio.billing(),
            'inventory': audio_store.setting('inventory'), 'capabilities': tts.MiniMaxTTS.capabilities,
            'fake_enabled': audio.config.get_env('WENSHU_FAKE_TTS') == '1'}


@router.put('/api/audio/limits')
def limits(request: Limits):
    return audio.set_limits(request)


@router.post('/api/audio/voices')
def voice(request: VoiceProfile):
    return audio.register_profile(request)


@router.put('/api/audio/voices/{pid}')
def change_voice(pid: str, request: VoiceProfile):
    return audio.register_profile(request,pid)


@router.post('/api/audio/inventory')
def inventory():
    return audio.query_inventory()
