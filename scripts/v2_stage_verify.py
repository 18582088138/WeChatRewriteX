"""Record a stage check against its actual source commit; never replay paid APIs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--summary', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A verification command is required')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    subprocess.run(['git', 'diff', '--exit-code'], cwd=ROOT, check=True, capture_output=True)
    output = ROOT / 'build' / 'v2-rebuild-evidence'
    output.mkdir(parents=True, exist_ok=True)
    log = output / f'{args.stage}.log'
    started = time.monotonic()
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with log.open('wb') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, **kwargs)
    report = {'stage': args.stage, 'branch': branch, 'source_commit': commit,
              'command': command, 'exit_code': result.returncode,
              'elapsed_seconds': round(time.monotonic() - started, 2),
              'log': log.relative_to(ROOT).as_posix(), 'new_paid_requests': 0, 'clone_requests': 0}
    (output / f'{args.stage}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if result.returncode:
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(result.returncode)
    destination = ROOT / 'docs' / 'v2' / 'rebuild' / f'{args.stage}.md'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f'# {args.stage} 重建验证记录\n\n{args.summary}\n\n'
        f'- 分支：`{branch}`\n- 源码提交：`{commit}`\n'
        f'- 验证命令：`{subprocess.list2cmdline(command)}`\n'
        f'- 结果：退出码 0；用时 {report["elapsed_seconds"]} 秒。\n'
        f'- 完整日志：`{report["log"]}`（本机忽略目录）。\n'
        '- 本阶段新增付费请求 0，克隆请求 0。真实人声、NUC/手机/跨网络与用户终审分开记录。\n'
        '- 数据/配置变化仅限源码与隔离测试；真实数据、`.env` 和旧安装包不改。\n'
        '- 回退：使用上一阶段分支/提交；数据库与文件回退先完整备份，在隔离目录恢复。\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
