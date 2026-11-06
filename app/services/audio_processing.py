"""Bounded local audio processing with measured paragraph timing."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import wave

_processing = threading.BoundedSemaphore(1)
MAX_DURATION = 600
MAX_BYTES = 64 * 1024 * 1024
FORMATS = {'.mp3':'mp3','.wav':'wav','.m4a':'mov','.aac':'aac','.ogg':'ogg','.flac':'flac'}


def input_args(path):
    value = FORMATS.get(Path(path).suffix.lower())
    if not value:
        raise ValueError('音频输入格式不受支持')
    # Force a media demuxer; uploaded playlists cannot reference other local files.
    return ['-protocol_whitelist','file,pipe','-f',value,'-i',str(path)]


def tool(name):
    from ..core.config import RUNTIME_ROOT
    override = os.environ.get('WENSHU_' + name.upper())
    bundled = RUNTIME_ROOT / 'audio-tools' / (name + ('.exe' if os.name == 'nt' else ''))
    value = override or (str(bundled) if bundled.is_file() else shutil.which(name))
    if not value or not Path(value).is_file():
        raise ValueError(f'缺少 {name}；请配置 WENSHU_{name.upper()} 或安装到 audio-tools/，保留已有成品')
    return value


def run(name, args, timeout=90):
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        result = subprocess.run([tool(name), *args], capture_output=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise ValueError('本地音频处理超时，未替换已有成品') from None
    if result.returncode:
        raise ValueError('本地音频处理失败；请检查素材格式/工具，未替换已有成品')
    return result


def probe(path):
    path = Path(path)
    if not path.is_file() or not 44 <= path.stat().st_size <= MAX_BYTES:
        raise ValueError('音频文件缺损或超过64MB上限')
    raw = run('ffprobe', ['-v', 'error', '-protocol_whitelist', 'file,pipe', '-f',FORMATS.get(path.suffix.lower(),'wav'), '-show_entries',
                         'format=duration:stream=codec_type,sample_rate,channels', '-of', 'json', str(path)], 20)
    try:
        data = json.loads(raw.stdout)
        duration = float(data['format']['duration'])
        if not 0 < duration <= MAX_DURATION or not any(s.get('codec_type') == 'audio' for s in data['streams']):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('音频时长或流信息无效，最长10分钟') from None
    # Decode the complete stream; a truncated file is never a valid cache hit.
    run('ffmpeg', ['-v', 'error', '-xerror', *input_args(path),
                   '-map', '0:a:0', '-f', 'null', '-'], 30)
    return duration


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
