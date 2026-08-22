import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/prove_v3_adversarial_failure.py"
FREEZE = ROOT / "docs/release/v3-candidate-freeze.json"
SPEC = importlib.util.spec_from_file_location("v3_adversarial_failure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
proof: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proof
SPEC.loader.exec_module(proof)


def _frozen_source_commit() -> str:
    payload = json.loads(FREEZE.read_text(encoding="utf-8"))
    return str(payload["candidate_source_commit"])


def _path_exists_in_frozen_source(path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{_frozen_source_commit()}:{path}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_g18_declares_exact_required_families_and_all_races() -> None:
    expected_races = {f"R{number:02d}" for number in range(1, 30)}
    assert set(proof.FAMILY_OWNERS) == {
        "attack_security",
        "race_concurrency",
        "crash_recovery",
        "retry_idempotency",
        "order_independence",
        "mutation_probes",
    }
    assert set(proof.RACE_NODES) == expected_races
    assert set(proof.RACE_OWNERS) == expected_races
    assert all(proof.RACE_NODES[race_id] for race_id in expected_races)
    node_selectors = (selector for selectors in proof.RACE_NODES.values() for selector in selectors)
    assert all("::" in selector for selector in node_selectors)


def test_g18_race_owners_are_derived_from_required_nodes() -> None:
    for race_id, selectors in proof.RACE_NODES.items():
        expected = tuple(sorted({selector.split("::", 1)[0] for selector in selectors}))
        assert proof.RACE_OWNERS[race_id] == expected


def test_g18_freezes_supporting_artifact_inventory() -> None:
    assert set(proof.SUPPORTING_ARTIFACTS) == {
        "test_collection",
        "test_junit",
        "concurrency_stability",
        "test_order_independence",
        "mutation_probes",
    }


def test_g18_every_declared_source_owner_existed_in_frozen_v3_source() -> None:
    source_owners = {
        owner
        for owners in proof.FAMILY_OWNERS.values()
        for owner in owners
        if not owner.startswith(".phase6/")
    } | {owner for owners in proof.RACE_OWNERS.values() for owner in owners}

    # Historical provenance answers whether the declared owner existed in the
    # source tree whose V3 evidence was frozen. Current head is intentionally
    # allowed to rename, replace or relocate that proof after an explicit
    # disposition, so checking ROOT / owner here would turn provenance back into
    # a current repository-shape freeze.
    missing = sorted(owner for owner in source_owners if not _path_exists_in_frozen_source(owner))
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


def test_g18_collection_inventory_requires_exact_unique_nodes(tmp_path: Path) -> None:
    artifact = tmp_path / "collection.json"
    node = "tests/db/test_example.py::test_example"
    artifact.write_text(
        json.dumps({"status": "PASS", "node_count": 1, "node_ids": [node]}),
        encoding="utf-8",
    )
    assert proof._collection_node_inventory(artifact) == ("PASS", {node}, [])

    artifact.write_text(
        json.dumps({"status": "PASS", "node_count": 2, "node_ids": [node, node]}),
        encoding="utf-8",
    )
    status, nodes, failures = proof._collection_node_inventory(artifact)
    assert status == "FAIL"
    assert nodes == {node}
    assert failures == ["test collection artifact contains duplicate node_ids"]

    artifact.write_text(
        json.dumps({"status": "PASS", "node_count": 2, "node_ids": [node]}),
        encoding="utf-8",
    )
    status, _, failures = proof._collection_node_inventory(artifact)
    assert status == "FAIL"
    assert failures == ["test collection node_count does not match node_ids inventory"]


def test_g18_selector_matching_accepts_param_cases_but_not_missing_tests() -> None:
    selector = "tests/db/test_example.py::test_example"
    assert proof._selector_collected(selector, {selector}) is True
    assert proof._selector_collected(selector, {f"{selector}[case-a]"}) is True
    assert proof._selector_collected(selector, {"tests/db/test_example.py::test_other"}) is False
