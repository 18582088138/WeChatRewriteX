"""Read-only rebuild prerequisites; deliberately contains no provider requests."""
import json
from pathlib import Path
import shutil
import subprocess
from app.core.environment import environment


def main():
    root = Path.cwd()
    values = environment.read(root / '.env')
    report = {'key_set': bool(values.get('MINIMAX_TTS_API_KEY')),
              'default_voice_set': bool(values.get('MINIMAX_DEFAULT_VOICE_ID')),
              'disk_free_gib': round(shutil.disk_usage(root).free / 2**30, 2)}
    assert report['key_set'] and report['default_voice_set']
    for name in ('ffmpeg', 'ffprobe'):
        tool = shutil.which(name)
        assert tool, f'{name} missing'
        report[name] = subprocess.check_output([tool, '-version'], text=True).splitlines()[0]
    assert subprocess.run(['git', 'merge-base', '--is-ancestor', 'cc59842', 'HEAD'], capture_output=True).returncode == 1
    assert not (root / 'app/services/audio.py').exists(), 'S0 must start without the original audio implementation'
    assert (root / 'AGENTS.md').is_file()
    ledger = json.loads((root / 'build/v2-evidence/real-smoke/ledger.json').read_text())
    report['historical_tts_attempts'] = ledger['tts_attempts']
    report['historical_sent_chars'] = ledger['sent_chars']
    report['new_paid_requests'] = report['clone_requests'] = 0
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
