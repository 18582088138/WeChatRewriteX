"""Audio endpoints stay under the current project authorization boundary."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field
from ..services import audio
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


@router.get(BASE + '/history')
def history(aid: str):
    return {'versions': audio.history(aid)}


class Revision(Strict):
    revision: int = Field(ge=1)


@router.post(BASE + '/confirm-source')
def confirm(aid: str, request: Revision):
    return audio.confirm_source(aid, request.revision)
