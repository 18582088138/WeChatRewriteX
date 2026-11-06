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


def pcm(source, target, trim_start=0, trim_seconds=None):
    probe(source)
    args = ['-v', 'error', '-nostdin', '-y', *input_args(source)]
    if trim_start:
        args += ['-ss', str(trim_start)]
    if trim_seconds:
        args += ['-t', str(trim_seconds)]
    run('ffmpeg', args + ['-map', '0:a:0', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(target)])
    probe(target)


def compose(segments, mix, media, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _processing:
        timeline, position, chunks = [], 0., []
        if media.get('intro'):
            path = directory / 'intro.wav'
            pcm(media['intro'], path, mix.trim_start, mix.trim_seconds)
            with wave.open(str(path), 'rb') as audio:
                frames = audio.readframes(audio.getnframes())
                position += audio.getnframes() / 24000
                chunks.append(frames)
        for index, (paragraph, segment) in enumerate(segments):
            path = directory / f'pcm-{index}.wav'
            pcm(segment, path)
            with wave.open(str(path), 'rb') as audio:
                frames = audio.readframes(audio.getnframes())
                duration = audio.getnframes() / 24000
            start, end = position, position + duration
            timeline.append({'paragraph_id': paragraph['id'], 'start': start, 'end': end,
                             'text': paragraph['text'], 'speech_text': paragraph['speech_text'],
                             'quality': 'paragraph'})
            chunks.extend([frames, b'\0\0' * int(paragraph['pause_ms'] * 24)])
            position = end + paragraph['pause_ms'] / 1000
        if media.get('outro'):
            path = directory / 'outro.wav'
            pcm(media['outro'], path, mix.trim_start, mix.trim_seconds)
            with wave.open(str(path), 'rb') as audio:
                chunks.append(audio.readframes(audio.getnframes()))
                position += audio.getnframes() / 24000
        if not 0 < position <= MAX_DURATION:
            raise ValueError('合成后时长须在0～10分钟内，请调整脚本')
        dry = directory / 'dry.wav'
        with wave.open(str(dry), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
            for chunk in chunks:
                audio.writeframes(chunk)
        input_path = dry
        if media.get('music'):
            music = directory / 'music.wav'
            pcm(media['music'], music, mix.trim_start, mix.trim_seconds)
            mixed = directory / 'mixed.wav'
            fade = min(mix.fade_seconds, position / 2)
            # Loop/crop music, fade both edges, then sidechain duck below narration.
            graph = (f'[1:a]volume={mix.music_gain},afade=t=in:d={fade},'
                     f'afade=t=out:st={max(0,position-fade)}:d={fade}[bg];'
                     '[0:a]asplit=2[voice][side];[bg][side]sidechaincompress=threshold=0.015:ratio=8[duck];'
                     '[voice][duck]amix=inputs=2:duration=first:normalize=0[out]')
            run('ffmpeg', ['-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(dry),
                           '-stream_loop', '-1', '-protocol_whitelist', 'file,pipe', '-i', str(music),
                           '-filter_complex', graph, '-map', '[out]', '-t', str(position), '-c:a', 'pcm_s16le', str(mixed)])
            input_path = mixed
        target = mix.loudness_lufs
        measurement = run('ffmpeg', ['-hide_banner', '-nostdin', '-protocol_whitelist', 'file,pipe', '-i', str(input_path),
                                     '-af', f'loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
        raw = measurement.stderr.decode('utf-8', errors='replace')
        try:
            report = json.loads(raw[raw.rfind('{'):raw.rfind('}')+1])
        except ValueError:
            raise ValueError('无法测量响度，保留已有成品') from None
        if any(report.get(k) in ('-inf', 'inf', 'nan') for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh')):
            raise ValueError('音频无有效可测声音，请检查输入')
        filter_value = (f'loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={report["input_i"]}:'
                        f'measured_TP={report["input_tp"]}:measured_LRA={report["input_lra"]}:'
                        f'measured_thresh={report["input_thresh"]}:offset={report["target_offset"]}:linear=true')
        wav = directory / 'audio.wav'
        run('ffmpeg', ['-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(input_path),
                       '-af', filter_value, '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
        mp3 = directory / 'audio.mp3'
        run('ffmpeg', ['-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(wav),
                       '-c:a', 'libmp3lame', '-b:a', '128k', str(mp3)])
        duration = probe(mp3)
        peak = run('ffmpeg', ['-hide_banner', '-nostdin', '-protocol_whitelist', 'file,pipe', '-i', str(mp3),
                              '-af', f'loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
        raw = peak.stderr.decode('utf-8', errors='replace')
        measured = json.loads(raw[raw.rfind('{'):raw.rfind('}')+1])
        if float(measured['input_tp']) >= 0:
            raise ValueError('成品检测到削波风险，请降低音量或调整混音')
        return {'duration': duration, 'timeline': timeline, 'loudness': {'target_lufs': target,
                'method': 'ffmpeg loudnorm two-pass; measured MP3', 'measured': measured},
                'within_target': 120 <= duration <= 300}


def subtitles(cues, vtt=False):
    def stamp(seconds):
        ms = round(seconds * 1000)
        h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f'{h:02}:{m:02}:{s:02}{"." if vtt else ","}{ms:03}'
    lines = ['WEBVTT', ''] if vtt else []
    for i, cue in enumerate(cues, 1):
        text = cue['text'].replace('-->', '→').replace('\r', '').replace('\n\n', '\n')
        lines.extend([str(i), f'{stamp(cue["start"])} --> {stamp(cue["end"])}', text, ''])
    return '\n'.join(lines)
