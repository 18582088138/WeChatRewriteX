"""Evidence ledger for two-host acceptance. Does not execute deployment or infer manual passes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = Path("docs/v1-plus/validation")
STATUSES = {"not_run", "running", "passed", "failed", "blocked", "not_applicable"}


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement; prior transitions are also retained in events.jsonl.
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def definitions():
    return {c["id"]: c for c in json.loads((ROOT / BASE / "cases.json").read_text(encoding="utf-8"))["cases"]}


def definitions_hash():
    handbook = ROOT / BASE / "CASEBOOK.md"
    criteria = {"cases": definitions(), "casebook": handbook.read_text(encoding="utf-8") if handbook.exists() else None}
    return hashlib.sha256(json.dumps(criteria, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def run_path(run_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,70}", run_id):
        raise ValueError("run-id must use 3–71 lowercase letters, digits or hyphens")
    path = ROOT / BASE / "runs" / run_id
    if path.is_symlink() or not path.resolve().is_relative_to((ROOT / BASE / "runs").resolve()):
        raise ValueError("Run directory must stay inside validation/runs")
    return path


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, encoding="utf-8").strip()


def init_run(run_id, machine_role, agent_label, binary=None):
    path = run_path(run_id)
    if path.exists():
        raise ValueError("Run already exists; continue it or use a new run-id")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Commit or preserve tracked changes before pinning the acceptance baseline")
    source = git("rev-parse", "HEAD")
    candidate = None
    if binary:
        binary = Path(binary).resolve(strict=True)
        candidate = {
            "version_output": subprocess.check_output([str(binary), "--version"], encoding="utf-8", timeout=30).strip(),
            "build": json.loads(subprocess.check_output([str(binary), "--build-info"], encoding="utf-8", timeout=30)),
            "executable_name": binary.name,
        }
    write(path / "run.json", {"schema": 1, "run_id": run_id, "machine_role": machine_role,
        "agent_label": agent_label, "source_commit": source, "criteria_sha256": definitions_hash(),
        "created_at_utc": now(), "candidate": candidate})
    write(path / "results.json", {cid: {"status": "not_run", "review": {"verdict": "pending"}} for cid in definitions()})
    (path / "evidence").mkdir()
    return path


def load(run_id):
    path = run_path(run_id)
    return path, json.loads((path / "run.json").read_text(encoding="utf-8")), json.loads((path / "results.json").read_text(encoding="utf-8"))


def evidence_item(path, run):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Evidence must be a non-empty file")
    shared = path.is_relative_to((run / "evidence").resolve())
    if shared and (path.suffix.lower() not in {".json", ".md", ".txt", ".csv"} or path.stat().st_size > 5 * 1024 * 1024):
        raise ValueError("Shared evidence must be a reviewed text report under 5 MiB; keep raw data/archives local")
    if shared:
        # Git may change CRLF/LF between hosts. Hash UTF-8 text with normalized
        # newlines, while private binary evidence retains its exact byte hash.
        digest = hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()
    else:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)
    return {"locator": path.relative_to(ROOT).as_posix() if shared else str(path),
            "visibility": "shared" if shared else "local_only", "bytes": path.stat().st_size,
            "hash_kind": "utf8_lf" if shared else "file_bytes", "sha256": digest}


def _digest(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def event(path, kind, case_id, old, new):
    with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at_utc": now(), "kind": kind, "case_id": case_id, "before": old, "after": new}, ensure_ascii=False) + "\n")


def record(run_id, case_id, status, summary, evidence=(), tested_commit=None, needed_input="", next_action=""):
    path, meta, results = load(run_id)
    case = definitions()[case_id]
    if meta["criteria_sha256"] != definitions_hash():
        raise ValueError("Case definitions changed; start a new run")
    if status not in STATUSES or not summary.strip():
        raise ValueError("A known status and factual summary are required")
    if status == "not_applicable" and case["required"]:
        raise ValueError("Required cases cannot be marked not_applicable; use blocked with the missing condition")
    if status in {"passed", "failed", "running"} and meta["machine_role"] != case["machine"]:
        raise ValueError("Company-machine results cannot count as NUC acceptance")
    if status == "passed" and tested_commit != meta["source_commit"]:
        raise ValueError("Pass must state the pinned source_commit; new product baseline requires a new run")
    items = [evidence_item(p, path) for p in evidence]
    if status in {"passed", "failed"} and not items:
        raise ValueError("Actual pass/failure requires evidence, not only a status label")
    if status == "blocked" and (not needed_input.strip() or not next_action.strip()):
        raise ValueError("Blocked requires the exact missing input and an actionable next step")
    if status in {"passed", "running"}:
        incomplete = [p for p in case["depends"] if results[p]["status"] != "passed"]
        if incomplete:
            raise ValueError("Prerequisites not passed: " + ", ".join(incomplete))
    new = {"status": status, "summary": summary, "at_utc": now(), "tested_commit": tested_commit,
           "evidence": items, "needed_input": needed_input, "next_action": next_action,
           "review": {"verdict": "pending"}}
    event(path, "record", case_id, results[case_id], new)
    results[case_id] = new
    write(path / "results.json", results)


def shared_proof_errors(path, row):
    errors = []
    for item in row.get("evidence", []):
        if item["visibility"] != "shared":
            continue
        target = (ROOT / item["locator"]).resolve()
        if not target.is_relative_to((path / "evidence").resolve()) or not target.is_file():
            errors.append("Shared evidence missing/outside run: " + item["locator"])
        elif evidence_item(target, path)["sha256"] != item["sha256"]:
            errors.append("Shared evidence changed: " + item["locator"])
    return errors


def review(run_id, case_id, verdict, reviewer, summary):
    path, meta, results = load(run_id)
    if not reviewer.strip() or not summary.strip():
        raise ValueError("Reviewer identity/alias and review reasoning are required")
    row = results[case_id]
    if verdict == "accepted":
        if row["status"] != "passed" or row.get("tested_commit") != meta["source_commit"]:
            raise ValueError("Only a pass on this baseline can be accepted")
        if not any(p["visibility"] == "shared" for p in row.get("evidence", [])):
            raise ValueError("Company review needs readable shared evidence; a local-only hash is insufficient")
        errors = shared_proof_errors(path, row)
        if errors:
            raise ValueError("; ".join(errors))
    new = {"verdict": verdict, "reviewer": reviewer, "summary": summary, "at_utc": now()}
    event(path, "review", case_id, row.get("review"), new)
    row["review"] = new
    write(path / "results.json", results)


def inspect_run(run_id):
    path, meta, results = load(run_id)
    cases = definitions()
    errors = []
    if meta.get("criteria_sha256") != definitions_hash() or set(results) != set(cases):
        errors.append("Case definitions changed; initialize a new run instead of inheriting old coverage")
    for cid, row in results.items():
        if cid not in cases or row.get("status") not in STATUSES:
            errors.append("Unknown case/status: " + cid)
            continue
        if row["status"] == "not_applicable" and cases[cid]["required"]:
            errors.append("Required case skipped: " + cid)
        if row["status"] == "passed":
            if meta["machine_role"] != "nuc" or row.get("tested_commit") != meta["source_commit"] or not row.get("evidence"):
                errors.append("Unsubstantiated/mismatched pass: " + cid)
            if any(results.get(dep, {}).get("status") != "passed" for dep in cases[cid]["depends"]):
                errors.append("Prerequisite invalidated: " + cid)
        if row["status"] == "failed" and not row.get("evidence"):
            errors.append("Failure has no execution evidence: " + cid)
        if row["status"] == "blocked" and (not row.get("needed_input") or not row.get("next_action")):
            errors.append("Blocked case has no actionable missing condition: " + cid)
        if row.get("review", {}).get("verdict") == "accepted":
            if (row["status"] != "passed" or not row["review"].get("reviewer") or not row["review"].get("summary")
                    or not any(p["visibility"] == "shared" for p in row.get("evidence", []))):
                errors.append("Acceptance has no readable reviewed evidence: " + cid)
        errors.extend(shared_proof_errors(path, row))
    gates = {}
    for group in ("local", "remote"):
        needed = [cid for cid, c in cases.items() if c["required"] and c["group"] == group]
        gates[group + "_reported"] = not errors and all(results.get(cid, {}).get("status") == "passed" for cid in needed)
        gates[group + "_reviewed"] = gates[group + "_reported"] and all(results[cid]["review"]["verdict"] == "accepted" for cid in needed)
    optional_resolved = all(
        results.get(cid, {}).get("status") == "not_applicable" or
        (results.get(cid, {}).get("status") == "passed" and results[cid]["review"]["verdict"] == "accepted")
        for cid, case in cases.items() if not case["required"])
    gates["final_reviewed"] = gates["local_reviewed"] and gates["remote_reviewed"] and optional_resolved
    return errors, gates


def render(run_id):
    path, meta, results = load(run_id)
    errors, gates = inspect_run(run_id)
    lines = [f"# NUC验收状态：{run_id}", "", f"固定源码：`{meta['source_commit']}`；报告机器：`{meta['machine_role']}`；生成时间UTC：{now()}。", "",
        "reported表示NUC记录；reviewed表示对共享材料的复核记录。工具校验结构和摘要，不会判断手工实验真实发生，也不会授权正式发布。", ""]
    lines.extend(f"- {key}: {str(value).lower()}" for key, value in gates.items())
    lines.append("")
    for cid, case in definitions().items():
        row = results.get(cid, {"status": "not_run", "review": {"verdict": "pending"}})
        lines.append(f"- **{cid} {case['title']}**：{row['status']}；复核：{row['review']['verdict']}。{row.get('summary', '')}")
        for proof in row.get("evidence", []):
            lines.append(f"  证据：{proof['visibility']}，`{proof['locator']}`，SHA256 `{proof['sha256']}`。")
        if row.get("needed_input"):
            lines.append(f"  缺项：{row['needed_input']}；下一步：{row['next_action']}。")
    if errors:
        lines.extend(["", "校验错误：", *[f"- {e}" for e in errors]])
    text = "\n".join(lines) + "\n"
    (path / "report.md").write_text(text, encoding="utf-8")
    (ROOT / BASE / "STATUS.md").write_text(text + "\n历史原始记录保留在各run目录；本文件是指定run的派生摘要。\n", encoding="utf-8")
    return errors, gates


def run_local(run_id, suite, attempt):
    """Run fixture-only checks in a new process, never with production runtime/env."""
    _, meta, _ = load(run_id)
    if not re.fullmatch(r"[a-z0-9-]{1,30}", attempt):
        raise ValueError("Use a short attempt label")
    code_paths = ("app", "scripts", "tests", "config", "web", "packaging", "pyproject.toml", "requirements.txt", ".env.example", "docs/v1-plus/validation/cases.json", "docs/v1-plus/validation/CASEBOOK.md")
    if git("diff", "--name-only", meta["source_commit"], "HEAD", "--", *code_paths) or git("diff", "--name-only", "HEAD", "--", *code_paths):
        raise ValueError("Test code/dependencies changed since pinned baseline; commit it and start a new run")
    raw = ROOT / "build/nuc-acceptance" / run_id
    raw.mkdir(parents=True, exist_ok=True)
    log, detail = raw / f"{suite}-{attempt}.log", raw / f"{suite}-{attempt}.json"
    if log.exists() or detail.exists():
        raise ValueError("Attempt exists; use a new label to preserve previous evidence")
    if suite == "backend":
        command = [sys.executable, "-X", "utf8", "-m", "pytest", "tests/", "-q", "--junitxml=" + str(raw / f"backend-{attempt}.xml")]
        cwd = ROOT
    else:
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            raise ValueError("Node/npm unavailable; install/confirm the existing verification environment")
        task = {"build": "build", "browser": "test:e2e", "team-browser": "test:team"}[suite]
        command = [npm, "run", task]
        cwd = ROOT / "web"
    started_at = now()
    started = time.monotonic()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    for key in list(env):
        if key.endswith(("_API_KEY", "_SEARCH_KEY")):
            env[key] = ""
    with tempfile.TemporaryDirectory(prefix="wenshu-acceptance-fixtures-") as fixture:
        # FixtureCrawler resolves tests/fixtures against PROJECT_ROOT, which
        # follows runtime. Copy only the repository's synthetic input corpus.
        corpus = ROOT / "tests/fixtures"
        if corpus.is_dir():
            shutil.copytree(corpus, Path(fixture) / "tests/fixtures")
        env.update(WENSHU_RUNTIME_DIR=fixture, WENSHU_DATA_DIR=str(Path(fixture) / "resource"),
                   WENSHU_LOG_DIR=str(Path(fixture) / "log"), WENSHU_TEAM_MODE="0", WENSHU_MIN_FREE_MB="1",
                   APP_ACCESS_TOKEN="", WENSHU_BOOTSTRAP_TOKEN="", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env["WENSHU_TEST_PYTHON"] = sys.executable
        with log.open("w", encoding="utf-8") as output:
            completed = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    baseline_valid = not (git("diff", "--name-only", meta["source_commit"], "HEAD", "--", *code_paths) or
                          git("diff", "--name-only", "HEAD", "--", *code_paths))
    exit_code = completed.returncode if baseline_valid else 1
    write(detail, {"run_id": run_id, "suite": suite, "attempt": attempt, "command": command,
                   "source_commit": meta["source_commit"], "started_at_utc": started_at, "ended_at_utc": now(),
                   "elapsed_seconds": round(time.monotonic() - started, 3), "exit_code": exit_code,
                   "suite_exit_code": completed.returncode, "baseline_valid": baseline_valid,
                   "python_version": sys.version.split()[0],
                   "scope": "Fixture-only subprocess; fresh runtime/data/log, team mode off in parent, external keys blanked",
                   "does_not_mark_case_passed": True})
    print(detail)
    if not baseline_valid:
        print("Code changed during verification; diagnostic output cannot pass the pinned baseline", file=sys.stderr)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "record", "review", "check", "report", "run-local"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        if name == "init":
            command.add_argument("--machine-role", choices=("nuc", "company"), required=True)
            command.add_argument("--agent-label", default="unknown")
            command.add_argument("--binary")
        elif name == "record":
            command.add_argument("--case", dest="case_id", required=True)
            command.add_argument("--status", choices=sorted(STATUSES), required=True)
            command.add_argument("--summary", required=True)
            command.add_argument("--evidence", action="append", default=[])
            command.add_argument("--tested-commit")
            command.add_argument("--needed-input", default="")
            command.add_argument("--next-action", default="")
        elif name == "review":
            command.add_argument("--case", dest="case_id", required=True)
            command.add_argument("--verdict", choices=("accepted", "needs_info"), required=True)
            command.add_argument("--reviewer", required=True)
            command.add_argument("--summary", required=True)
        elif name == "check":
            command.add_argument("--gate", choices=("local_reported", "local_reviewed", "remote_reported", "remote_reviewed", "final_reviewed"))
        elif name == "run-local":
            command.add_argument("--suite", choices=("backend", "build", "browser", "team-browser"), required=True)
            command.add_argument("--attempt", required=True)
    args = vars(parser.parse_args())
    name = args.pop("command")
    try:
        if name == "init":
            print(init_run(**args))
        elif name == "record":
            record(**args)
        elif name == "review":
            review(**args)
        elif name == "run-local":
            return run_local(**args)
        else:
            gate = args.pop("gate", None)
            errors, gates = render(**args) if name == "report" else inspect_run(**args)
            print(json.dumps({"errors": errors, "gates": gates}, ensure_ascii=False, indent=2))
            if errors:
                return 1
            if gate and not gates[gate]:
                return 2
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
