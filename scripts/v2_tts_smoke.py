"""One real short synthesis with a persistent, non-resetting developer ledger."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--voice-id',required=True)
    parser.add_argument('--directory',default='build/v2-evidence/real-smoke')
    args=parser.parse_args()
    directory=Path(args.directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    ledger_path=directory/'ledger.json'
    ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {'tts_attempts':0,'sent_chars':0,'clone_attempts':0,'attempts':[]}
    text='这是一段音频创作测试。今天，我们用清晰自然的声音，讲述科技新闻。'
    if ledger['tts_attempts']>=2 or ledger['sent_chars']+len(text)>120:
        raise SystemExit('Developer TTS budget exhausted; no request sent')
    from app.services.tts import MiniMaxTTS,TTSError
    from app.services.audio_models import VoiceSettings
    from app.services.audio_processing import probe,checksum
    entry={'voice_id':args.voice_id,'model':'speech-2.6-hd','chars':len(text),'at':time.time(),'state':'sending'}
    ledger['tts_attempts']+=1;ledger['sent_chars']+=len(text);ledger['attempts'].append(entry)
    ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        result=MiniMaxTTS().synthesize(text,{'voice_id':args.voice_id},VoiceSettings(),'zh')
        path=directory/f'sample-{ledger["tts_attempts"]}.mp3';path.write_bytes(result.audio)
        entry.update(state='completed',duration=probe(path),sha256=checksum(path),request_id=result.request_id,
                     usage_characters=result.usage_characters,audio=str(path),cost_status='official-rate estimate; pending account bill')
        if result.usage_characters is not None:entry['estimated_cny']=result.usage_characters*3.5/10000
    except TTSError as exc:
        entry.update(state=exc.state,error=str(exc))
    ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(ledger,ensure_ascii=False))


if __name__=='__main__':main()
