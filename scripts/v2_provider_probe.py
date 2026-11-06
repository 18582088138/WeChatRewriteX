"""Read-only MiniMax inventory/doc probe. No upload/clone/delete endpoints."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    from app.core import config
    from app.services.http import client_for
    urls = [
        'https://platform.minimaxi.com/docs/api-reference/voice-management-get',
        'https://platform.minimaxi.com/docs/api-reference/speech-t2a-http',
        'https://platform.minimaxi.com/docs/guides/pricing-pay-as-you-go',
    ]
    out = {'key_set': bool(config.get_env('MINIMAX_TTS_API_KEY')),
           'inventory_attempts': 0, 'tts_attempts': 0, 'clone_attempts': 0, 'docs': []}
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls):
        entry = {'url': url}
        try:
            with client_for(url, timeout=12) as client:
                response = client.get(url)
            entry['status'] = response.status_code
            if response.status_code == 200:
                (dest.parent / f'official-{i}.html').write_text(response.text, encoding='utf-8')
        except Exception as exc:
            entry['error'] = type(exc).__name__  # Never print response bodies or credentials.
        out['docs'].append(entry)
        print(json.dumps(entry), flush=True)
    if out['key_set']:
        out['inventory_attempts'] = 1
        url = 'https://api.minimaxi.com/v1/get_voice'
        try:
            with client_for(url, timeout=15) as client:
                response = client.post(url, headers={'Authorization': 'Bearer ' + config.get_env('MINIMAX_TTS_API_KEY')},
                                       json={'voice_type': 'voice_cloning'})
            out['inventory_http'] = response.status_code
            data = response.json()
            out['provider_code'] = data.get('base_resp', {}).get('status_code')
            out['voices'] = [{'voice_id': v.get('voice_id'), 'name': v.get('voice_name') or v.get('voice_id')}
                             for v in data.get('voice_cloning', [])]
        except Exception as exc:
            out['inventory_error'] = type(exc).__name__
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
