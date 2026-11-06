"""Typecheck/build then exercise the current audio workbench in a disposable server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, WENSHU_TEST_PYTHON=sys.executable)
    npm = ['cmd', '/c', 'npm'] if os.name == 'nt' else ['npm']
    commands = [['run', 'build'], ['run', 'test:audio', '--', 'stages.spec.ts']]
    if args.all:
        commands = [['run', 'build'], ['run', 'test:e2e'], ['run', 'test:team'], ['run', 'test:audio']]
    for command in commands:
        subprocess.run(npm + command, cwd=root/'web', env=env, check=True)


if __name__ == '__main__':
    main()
