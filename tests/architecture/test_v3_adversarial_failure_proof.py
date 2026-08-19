import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/release/prove_v3_adversarial_failure.py"
SPEC = importlib.util.spec_from_file_location("v3_adversarial_failure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
proof: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proof
SPEC.loader.exec_module(proof)


def test_g18_declares_exact_required_families_and_all_races() -> None:
    assert set(proof.FAMILY_OWNERS) == {
        "attack_security",
        "race_concurrency",
        "crash_recovery",
        "retry_idempotency",
        "order_independence",
        "mutation_probes",
    }
    assert set(proof.RACE_OWNERS) == {f"R{number:02d}" for number in range(1, 30)}
    assert all(proof.RACE_OWNERS[race_id] for race_id in proof.RACE_OWNERS)


def test_g18_freezes_supporting_artifact_inventory() -> None:
    assert set(proof.SUPPORTING_ARTIFACTS) == {
        "test_collection",
        "test_junit",
        "concurrency_stability",
        "test_order_independence",
        "mutation_probes",
    }


def test_g18_every_declared_source_owner_exists() -> None:
    source_owners = {
        owner
        for owners in proof.FAMILY_OWNERS.values()
        for owner in owners
        if not owner.startswith(".phase6/")
    } | {owner for owners in proof.RACE_OWNERS.values() for owner in owners}
    missing = sorted(owner for owner in source_owners if not (proof.ROOT / owner).is_file())
    assert missing == []


def test_g18_junit_validator_rejects_failures_errors_and_skips(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite tests="5" failures="1" errors="1" skipped="1"/>',
        encoding="utf-8",
    )
    status, counts, failures = proof._junit_status(junit)
    assert status == "FAIL"
    assert counts == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}
    assert "JUnit contains 1 failures" in failures
    assert "JUnit contains 1 errors" in failures
    assert "JUnit contains 1 skipped" in failures


def test_g18_json_status_requires_real_pass_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof, "ROOT", tmp_path)
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"status":"PASS"}\n', encoding="utf-8")
    assert proof._json_status(artifact) == ("PASS", [])

    artifact.write_text('{"status":"FAIL"}\n', encoding="utf-8")
    status, failures = proof._json_status(artifact)
    assert status == "FAIL"
    assert failures
