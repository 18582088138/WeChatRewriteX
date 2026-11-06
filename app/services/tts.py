"""TTS providers. The only remote operations are inventory and synthesis."""
from dataclasses import dataclass
import hashlib
import io
import math
import struct
import wave
import httpx
from ..core import config
from .http import client_for

ALLOWED_ORIGINS = ('https://api.minimaxi.com', 'https://api.minimax.io')
MAX_AUDIO_BYTES = 32 * 1024 * 1024


class TTSError(ValueError):
    def __init__(self, message, state='failed'):
        super().__init__(message)
        self.state = state


@dataclass
class TTSResult:
    audio: bytes
    extension: str
    request_id: str | None = None
    usage_characters: int | None = None


class FakeTTS:
    capabilities = {'provider': 'fake', 'label': '离线测试音（非人声）', 'timestamps': 'paragraph',
                    'emotion': False, 'ssml': False, 'state_query': False}

    def synthesize(self, text, voice, settings, language):
        # Real WAV bytes, deterministically dependent on input. Never resembles clone validation.
        duration = max(.25, min(3, len(text) / 10))
        freq = 220 + int(hashlib.sha256(text.encode()).hexdigest()[:4], 16) % 180
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
            frames = bytearray()
            for n in range(int(duration * 24000)):
                envelope = min(1, n / 240, (duration * 24000 - n) / 240)
                frames.extend(struct.pack('<h', int(1200 * envelope * math.sin(2 * math.pi * freq * n / 24000))))
            audio.writeframes(frames)
        return TTSResult(stream.getvalue(), 'wav')


def origin():
    value = config.get_env('MINIMAX_TTS_ORIGIN') or ALLOWED_ORIGINS[0]
    if value not in ALLOWED_ORIGINS:
        raise TTSError('MiniMax 区域地址须为受支持的官方 HTTPS 域名')
    return value


class MiniMaxTTS:
    capabilities = {'provider': 'minimax', 'timestamps': 'paragraph', 'emotion': False,
                    'ssml': False, 'state_query': False, 'speed': [0.5, 2], 'pitch': [-12, 12],
                    'models': ['speech-2.6-hd', 'speech-2.6-turbo', 'speech-02-hd', 'speech-02-turbo'],
                    'validation': '待当前账号短文本验证'}

    def synthesize(self, text, voice, settings, language):
        key = config.get_env('MINIMAX_TTS_API_KEY')
        if not key:
            raise TTSError('未配置 MINIMAX_TTS_API_KEY', 'not_sent')
        url = origin() + '/v1/t2a_v2'
        payload = {'model': settings.model, 'text': text, 'stream': False,
                   'voice_setting': {'voice_id': voice['voice_id'], 'speed': settings.speed,
                                     'vol': settings.volume, 'pitch': settings.pitch},
                   'audio_setting': {'sample_rate': 24000, 'bitrate': 128000, 'format': 'mp3', 'channel': 1},
                   'language_boost': 'Chinese' if language == 'zh' else 'English', 'output_format': 'hex'}
        try:
            with client_for(url, timeout=60) as client:
                # No retries, redirects or remote audio URL downloads.
                with client.stream('POST', url, headers={'Authorization': 'Bearer ' + key}, json=payload) as response:
                    if response.status_code != 200:
                        raise TTSError(f'MiniMax HTTP {response.status_code}，未自动重试',
                                       'unknown' if response.status_code >= 500 else 'failed')
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_AUDIO_BYTES * 2 + 65536:
                            raise TTSError('服务商响应超过音频大小上限', 'unknown')
            import json
            data = json.loads(raw)
            code = data.get('base_resp', {}).get('status_code')
            if code != 0:
                meaning = {1008:'账户余额不足，请检查 MiniMax 账户余额',1004:'鉴权失败，请检查服务端密钥',
                           1002:'触发限流，未自动重试',1039:'触发文本量限流，未自动重试',2013:'输入参数无效，请检查模型及已有音色'}.get(code,'请核对服务商账户、模型及已有音色')
                raise TTSError(f'MiniMax 错误代码 {code}：{meaning}；不会重新克隆或自动换音色',
                               'unknown' if code in (1000,1001,1024,1033) else 'failed')
            encoded = data.get('data', {}).get('audio')
            if not isinstance(encoded, str) or not encoded:
                raise TTSError('响应缺少音频，费用待核对', 'unknown')
            audio = bytes.fromhex(encoded)
            if not audio or len(audio) > MAX_AUDIO_BYTES:
                raise TTSError('音频内容为空或超限', 'unknown')
            usage = data.get('extra_info', {}).get('usage_characters')
            return TTSResult(audio, 'mp3', str(data.get('trace_id') or '')[:150], usage if isinstance(usage,int) and usage >= 0 else None)
        except TTSError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise TTSError('MiniMax 响应未知；可能已计费，需人工确认后另建尝试', 'unknown') from None


def provider(name):
    if name == 'minimax':
        return MiniMaxTTS()
    if name == 'fake' and config.get_env('WENSHU_FAKE_TTS') == '1':
        return FakeTTS()
    raise TTSError('离线测试音仅在 WENSHU_FAKE_TTS=1 时可用，不会自动替换音色', 'not_sent')


def inventory():
    key = config.get_env('MINIMAX_TTS_API_KEY')
    if not key:
        raise TTSError('未配置 MINIMAX_TTS_API_KEY', 'not_sent')
    url = origin() + '/v1/get_voice'
    try:
        with client_for(url, timeout=15) as client:
            response = client.post(url, headers={'Authorization': 'Bearer ' + key}, json={'voice_type': 'voice_cloning'})
        if response.status_code != 200:
            raise TTSError(f'音色查询 HTTP {response.status_code}')
        data = response.json()
        if data.get('base_resp', {}).get('status_code') != 0:
            raise TTSError('音色查询失败；不代表账号没有已有音色')
        return [{'voice_id': v['voice_id'], 'name': v.get('voice_name') or v['voice_id']}
                for v in data.get('voice_cloning', []) if isinstance(v.get('voice_id'), str)]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise TTSError('音色查询未成功；可登记已知 ID，标记待验证；没有创建音色') from None
