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


@router.post(BASE + '/review-ai')
def ai_review(aid: str,request: Revision):
    return audio.ai_review(aid,request.revision)


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


@router.post(BASE + '/reviews')
def submit(aid: str, request: SubmitReview):
    return audio.submit_review(aid, request)


@router.put(BASE + '/reviews/{sid}')
def decide(aid: str, sid: str, request: ReviewAction):
    return audio.decide_review(aid, sid, request)


class Comment(Strict):
    revision: int = Field(ge=0)
    paragraph_id: str = Field(max_length=80)
    message: str = Field(min_length=1, max_length=2000)


@router.post(BASE + '/reviews/{sid}/comments')
def comment(aid: str, sid: str, request: Comment):
    return audio.comment(aid, sid, request.revision, request.paragraph_id, request.message)


class ResolveComment(Strict):
    revision: int = Field(ge=0)
    status: str = Field(pattern='^(resolved|declined)$')
    reason: str = Field(default='',max_length=2000)


@router.put(BASE + '/review-comments/{sid}/{cid}')
def resolve(aid: str,sid: str,cid: str,request: ResolveComment):
    return audio.resolve_comment(aid,sid,cid,request.revision,request.status,request.reason)


class Export(Strict):
    batch_id: str


@router.post(BASE + '/export')
def export(aid: str, request: Export):
    return audio.export(aid, request.batch_id)


@router.get(BASE + '/exports/{name}')
def download(aid: str, name: str):
    import json
    from ..storage import db
    from fastapi import HTTPException
    audio.project(aid)
    row = db.query_one('SELECT manifest_json FROM audio_exports WHERE article_id=?', (aid,))
    if not row:
        raise HTTPException(404, '暂无正式音频导出')
    manifest = json.loads(row['manifest_json'])
    f = next((f for f in manifest['files'] if f['name']==name), None)
    if not f:
        raise HTTPException(404, '导出文件不存在')
    return FileResponse(audio.file_path(aid,f['id']), filename=name, headers={'Cache-Control':'no-store'})


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
