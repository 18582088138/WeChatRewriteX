"""Build once, then independently check backend and disposable browsers."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    npm = ['cmd', '/c', 'npm'] if os.name == 'nt' else ['npm']
    subprocess.run(npm+['run','build'], cwd=root/'web', check=True)
    evidence = root/'build/v2-rebuild-evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    checks = {
        'backend-final': [sys.executable, '-X', 'utf8', '-m', 'pytest', 'tests/', '-q'],
        'browser-final': [sys.executable, '-X', 'utf8', 'scripts/v2_web_verify.py', '--all', '--skip-build'],
    }
    def verify(item):
        name, command = item
        started = time.monotonic()
        with (evidence/f'{name}.log').open('wb') as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        return {'check':name,'exit_code':result.returncode,'elapsed_seconds':round(time.monotonic()-started,2)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, checks.items()))
    print(json.dumps(results))
    if any(result['exit_code'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
