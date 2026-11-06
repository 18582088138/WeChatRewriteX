"""Validated persisted audio inputs; no arbitrary endpoints, paths or commands."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Paragraph(Strict):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    text: str = Field(max_length=4000)
    speech_text: str = Field(max_length=4000)
    manual_speech: bool = False
    source_block_ids: list[str] = Field(default_factory=list, max_length=100)
    citations: list[str] = Field(default_factory=list, max_length=100)
    pause_ms: int = Field(default=300, ge=0, le=3000)


class Brief(Strict):
    audience: str = Field(default='科技资讯读者', max_length=300)
    persona: str = Field(default='清晰、自然、准确', max_length=300)
    language: Literal['zh', 'en'] = 'zh'
    target_seconds: int = Field(default=180, ge=120, le=300)
    purpose: str = Field(default='单人旁白', max_length=300)


class VoiceSettings(Strict):
    profile_id: str = Field(default='', max_length=80)
    model: Literal['speech-2.6-hd', 'speech-2.6-turbo', 'speech-02-hd', 'speech-02-turbo'] = 'speech-2.6-hd'
    speed: float = Field(default=1, ge=0.5, le=2)
    pitch: int = Field(default=0, ge=-12, le=12)
    volume: float = Field(default=1, gt=0, le=10)


class Mix(Strict):
    intro_id: str | None = None
    outro_id: str | None = None
    music_id: str | None = None
    music_gain: float = Field(default=0.08, ge=0, le=0.25)
    trim_start: float = Field(default=0, ge=0, le=300)
    trim_seconds: float = Field(default=30, ge=0.5, le=120)
    fade_seconds: float = Field(default=1, ge=0, le=5)
    loudness_lufs: float = Field(default=-16, ge=-24, le=-12)
    license_note: str = Field(default='', max_length=1000)


class SpeechDoc(Strict):
    title: str = Field(default='', max_length=300)
    brief: Brief = Field(default_factory=Brief)
    paragraphs: list[Paragraph] = Field(default_factory=list, max_length=80)
    dictionary: dict[str, str] = Field(default_factory=dict, max_length=100)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    mix: Mix = Field(default_factory=Mix)
    source_hash: str = ''
    source_version: int | None = None
    source_revision: int | None = None
    source_confirmed_hash: str = ''
    rules_version: str = 'speech-rules-1'


class SaveSpeech(Strict):
    revision: int = Field(ge=0)
    doc: SpeechDoc


class Derive(Strict):
    revision: int = Field(default=0, ge=0)
    brief: Brief = Field(default_factory=Brief)
    use_llm: bool = False


class VoiceProfile(Strict):
    provider: Literal['minimax', 'fake'] = 'minimax'
    voice_id: str = Field(min_length=1, max_length=150, pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1, max_length=100)
    authorization: str = Field(min_length=1, max_length=1500)
    projects: list[str] = Field(min_length=1, max_length=100)
    enabled: bool = True


class Limits(Strict):
    max_requests: int = Field(default=2, ge=0, le=10000)
    max_chars: int = Field(default=120, ge=0, le=1000000)
    max_estimated_cost: float | None = Field(default=None, ge=0, le=10000)
    rate_per_10k: float | None = Field(default=None, ge=0, le=1000)
    rate_model: str = Field(default='speech-2.6-hd', max_length=80)
    rate_source: str = Field(default='', max_length=1000)
    rate_effective: str = Field(default='', max_length=80)
    currency: Literal['CNY'] = 'CNY'


class Generate(Strict):
    revision: int = Field(ge=1)
    paragraph_ids: list[str] | None = Field(default=None, max_length=80)
    confirm_unknown_retry: bool = False


class ReviewAction(Strict):
    revision: int = Field(default=0, ge=0)
    status: Literal['approved', 'returned']
    reason: str = Field(default='', max_length=2000)


class SubmitReview(Strict):
    kind: Literal['script', 'audio']
    revision: int = Field(ge=1)
    batch_id: str | None = None
    reviewer_id: str | None = None


class Rewrite(Strict):
    revision: int = Field(ge=1)
    paragraph_id: str
    instruction: str = Field(min_length=1, max_length=1000)


class SubtitleCue(Strict):
    paragraph_id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=4000)


class Subtitles(Strict):
    cues: list[SubtitleCue] = Field(max_length=80)
