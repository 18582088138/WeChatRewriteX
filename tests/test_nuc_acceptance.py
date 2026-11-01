import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import nuc_acceptance as ledger

COMMIT = "a" * 40


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    monkeypatch.setattr(ledger, "git", lambda *args: "" if args[0] == "status" else COMMIT)
    base = tmp_path / ledger.BASE
    base.mkdir(parents=True)
    cases = [
        {"id": "B01", "title": "Baseline", "group": "local", "machine": "nuc", "required": True, "depends": []},
        {"id": "B02", "title": "Local", "group": "local", "machine": "nuc", "required": True, "depends": ["B01"]},
        {"id": "R01", "title": "Remote", "group": "remote", "machine": "nuc", "required": True, "depends": ["B02"]},
    ]
    ledger.write(base / "cases.json", {"schema": 1, "cases": cases})
    return ledger.init_run("nuc-test-01", "nuc", "test-agent")


def proof(run, name="baseline.md"):
    path = run / "evidence" / name
    path.write_text("Synthetic test observation; not a real NUC acceptance.\n", encoding="utf-8")
    return path


def pass_case(run, cid):
    ledger.record("nuc-test-01", cid, "passed", "Observed fixture", [proof(run, cid + ".md")], COMMIT)


def test_initial_run_never_inherits_historical_passes(run):
    errors, gates = ledger.render("nuc-test-01")
    assert not errors and not any(gates.values())
    assert "not_run" in (run / "report.md").read_text(encoding="utf-8")


def test_pass_requires_evidence_baseline_and_target_host(run, tmp_path):
    with pytest.raises(ValueError, match="requires evidence"):
        ledger.record("nuc-test-01", "B01", "passed", "Unsubstantiated", tested_commit=COMMIT)
    with pytest.raises(ValueError, match="pinned"):
        ledger.record("nuc-test-01", "B01", "passed", "Wrong build", [proof(run)], "b" * 40)
    ledger.init_run("company-test", "company", "test-agent")
    with pytest.raises(ValueError, match="Company"):
        ledger.record("company-test", "B01", "passed", "Company evidence", [proof(run)], COMMIT)


def test_prerequisites_and_required_cases_cannot_be_skipped(run):
    with pytest.raises(ValueError, match="Prerequisites"):
        ledger.record("nuc-test-01", "B02", "passed", "Too early", [proof(run)], COMMIT)
    with pytest.raises(ValueError, match="not_applicable"):
        ledger.record("nuc-test-01", "R01", "not_applicable", "No remote member")
    with pytest.raises(ValueError, match="exact missing"):
        ledger.record("nuc-test-01", "R01", "blocked", "No remote member")
    ledger.record("nuc-test-01", "R01", "blocked", "Awaiting member", needed_input="Phone and remote member", next_action="Schedule real-network test")
    assert not ledger.inspect_run("nuc-test-01")[0]


def test_local_only_hash_is_not_company_review(run, tmp_path):
    local = tmp_path / "private-log.txt"
    local.write_text("fixture", encoding="utf-8")
    ledger.record("nuc-test-01", "B01", "passed", "Local run", [local], COMMIT)
    with pytest.raises(ValueError, match="readable shared"):
        ledger.review("nuc-test-01", "B01", "accepted", "company-agent", "Read it")


def test_review_and_hash_change_invalidate_gates(run):
    pass_case(run, "B01")
    ledger.review("nuc-test-01", "B01", "accepted", "company-agent", "Reviewed observations")
    (run / "evidence/B01.md").write_text("Changed after review", encoding="utf-8")
    errors, gates = ledger.inspect_run("nuc-test-01")
    assert any("changed" in e for e in errors) and not any(gates.values())


def test_local_completion_does_not_complete_remote_acceptance(run):
    for cid in ("B01", "B02"):
        pass_case(run, cid)
        ledger.review("nuc-test-01", cid, "accepted", "company-agent", "Reviewed fixture")
    errors, gates = ledger.inspect_run("nuc-test-01")
    assert not errors and gates["local_reviewed"] and not gates["final_reviewed"]
    pass_case(run, "R01")
    assert ledger.inspect_run("nuc-test-01")[1]["remote_reported"]
    assert not ledger.inspect_run("nuc-test-01")[1]["final_reviewed"]
    ledger.review("nuc-test-01", "R01", "accepted", "company-agent", "Reviewed remote fixture")
    assert ledger.inspect_run("nuc-test-01")[1]["final_reviewed"]


def test_retest_resets_review_and_keeps_history(run):
    pass_case(run, "B01")
    ledger.review("nuc-test-01", "B01", "accepted", "company-agent", "Reviewed")
    pass_case(run, "B01")
    _, _, results = ledger.load("nuc-test-01")
    assert results["B01"]["review"]["verdict"] == "pending"
    events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(events) == 3 and events[-1]["before"]["review"]["verdict"] == "accepted"


def test_definition_changes_cannot_reuse_old_coverage(run):
    file = ledger.ROOT / ledger.BASE / "cases.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["cases"][0]["title"] = "New criterion"
    ledger.write(file, data)
    errors, gates = ledger.inspect_run("nuc-test-01")
    assert errors and not any(gates.values())


def test_hand_edited_review_without_shared_evidence_is_rejected(run, tmp_path):
    local = tmp_path / "local.txt"
    local.write_text("fixture", encoding="utf-8")
    ledger.record("nuc-test-01", "B01", "passed", "Local", [local], COMMIT)
    _, _, rows = ledger.load("nuc-test-01")
    rows["B01"]["review"] = {"verdict": "accepted", "reviewer": "company", "summary": "Unsupported"}
    ledger.write(run / "results.json", rows)
    assert ledger.inspect_run("nuc-test-01")[0]


def test_run_path_cannot_escape_or_replace_an_existing_run(run):
    with pytest.raises(ValueError):
        ledger.run_path("../outside")
    with pytest.raises(ValueError, match="already exists"):
        ledger.init_run("nuc-test-01", "nuc", "agent")


def test_fixture_runner_never_inherits_production_runtime_or_keys(run, tmp_path, monkeypatch):
    production = tmp_path / "production-runtime"
    production.mkdir()
    secret = production / ".env"
    secret.write_text("OPENAI_API_KEY=fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("WENSHU_RUNTIME_DIR", str(production))
    monkeypatch.setenv("WENSHU_DATA_DIR", str(production / "resource"))
    monkeypatch.setenv("WENSHU_TEAM_MODE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    monkeypatch.setattr(ledger, "git", lambda *args: "" if args[0] in {"status", "diff"} else COMMIT)
    captured = {}
    def execute(command, **kwargs):
        captured.update(kwargs["env"])
        kwargs["stdout"].write("Synthetic runner fixture\n")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(ledger.subprocess, "run", execute)
    assert ledger.run_local("nuc-test-01", "backend", "01") == 0
    assert captured["WENSHU_RUNTIME_DIR"] != str(production)
    assert captured["WENSHU_TEAM_MODE"] == "0" and captured["OPENAI_API_KEY"] == ""
    assert not Path(captured["WENSHU_RUNTIME_DIR"]).exists()
    assert secret.read_text(encoding="utf-8") == "OPENAI_API_KEY=fixture-secret\n"
    assert ledger.load("nuc-test-01")[2]["B01"]["status"] == "not_run"
    with pytest.raises(ValueError, match="Attempt exists"):
        ledger.run_local("nuc-test-01", "backend", "01")


def test_runner_refuses_changed_test_source(run, monkeypatch):
    monkeypatch.setattr(ledger, "git", lambda *args: "scripts/changed.py" if args[0] == "diff" else COMMIT)
    with pytest.raises(ValueError, match="changed since pinned"):
        ledger.run_local("nuc-test-01", "backend", "01")


def test_handbook_change_invalidates_existing_acceptance(run):
    (ledger.ROOT / ledger.BASE / "CASEBOOK.md").write_text("A new acceptance threshold", encoding="utf-8")
    assert ledger.inspect_run("nuc-test-01")[0]


def test_shared_text_hash_survives_git_line_ending_conversion(run):
    path = proof(run)
    path.write_bytes(b"First observation\r\nSecond observation\r\n")
    ledger.record("nuc-test-01", "B01", "passed", "Observed", [path], COMMIT)
    ledger.review("nuc-test-01", "B01", "accepted", "company-agent", "Read observations")
    path.write_bytes(b"First observation\nSecond observation\n")
    assert not ledger.inspect_run("nuc-test-01")[0]
    path.write_bytes(b"Changed observation\nSecond observation\n")
    assert ledger.inspect_run("nuc-test-01")[0]


def test_selected_optional_route_must_be_resolved_before_final_gate(run):
    file = ledger.ROOT / ledger.BASE / "cases.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["cases"].append({"id": "X01", "title": "Optional route", "group": "optional", "machine": "nuc", "required": False, "depends": []})
    ledger.write(file, data)
    ledger.init_run("optional-test", "nuc", "agent")
    for cid in ("B01", "B02", "R01"):
        path = run.parent / "optional-test/evidence" / (cid + ".md")
        path.write_text("Fixture observation", encoding="utf-8")
        ledger.record("optional-test", cid, "passed", "Observed fixture", [path], COMMIT)
        ledger.review("optional-test", cid, "accepted", "company-agent", "Read observations")
    assert not ledger.inspect_run("optional-test")[1]["final_reviewed"]
    ledger.record("optional-test", "X01", "not_applicable", "Windows route selected; Docker not used")
    assert ledger.inspect_run("optional-test")[1]["final_reviewed"]
