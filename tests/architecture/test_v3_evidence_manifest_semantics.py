import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/release/build_v3_evidence_manifest.py"
SPEC = importlib.util.spec_from_file_location("v3_evidence_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
manifest: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manifest
SPEC.loader.exec_module(manifest)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_artifacts(root: Path) -> dict[str, Path]:
    paths = {
        name: root / filename
        for name, filename in {
            "schema_fingerprint": "schema.json",
            "catalog_audit": "catalog.json",
            "worker_query_plans": "plans.json",
            "initial_equivalence": "equivalence.txt",
            "test_quality": "quality.json",
            "test_collection": "collection.json",
            "test_junit": "junit.xml",
            "concurrency_stability": "concurrency.json",
            "test_order_independence": "order.json",
            "mutation_probes": "mutation.json",
        }.items()
    }
    _write_json(paths["schema_fingerprint"], {"schemas": ["request_engine"]})
    _write_json(paths["catalog_audit"], {"errors": [], "warnings": []})
    _write_json(
        paths["worker_query_plans"],
        {"proofs": [{"required_index": "due_idx", "indexes": ["due_idx"]}]},
    )
    paths["initial_equivalence"].write_text(
        "catalog-equivalent to the V3 candidate chain", encoding="utf-8"
    )
    for name in (
        "test_quality",
        "test_collection",
        "concurrency_stability",
        "test_order_independence",
        "mutation_probes",
    ):
        _write_json(paths[name], {"status": "PASS"})
    paths["test_junit"].write_text(
        '<testsuite tests="3" failures="0" errors="0" skipped="0"/>',
        encoding="utf-8",
    )
    return paths


def test_evidence_bundle_semantics_accept_actual_pass_results(tmp_path: Path) -> None:
    assert manifest._validate_artifacts(_valid_artifacts(tmp_path)) == []


def test_evidence_bundle_semantics_reject_failed_json_proofs(tmp_path: Path) -> None:
    mutations: list[tuple[str, object, str]] = [
        ("test_quality", {"status": "FAIL"}, "expected 'PASS'"),
        ("catalog_audit", {"errors": [{"kind": "unsafe"}]}, "catalog errors"),
        (
            "worker_query_plans",
            {"proofs": [{"required_index": "due_idx", "indexes": []}]},
            "required index",
        ),
    ]
    for artifact, payload, expected in mutations:
        paths = _valid_artifacts(tmp_path)
        _write_json(paths[artifact], payload)
        assert expected in " ".join(manifest._validate_artifacts(paths))


def test_evidence_bundle_semantics_reject_failed_or_skipped_junit(tmp_path: Path) -> None:
    paths = _valid_artifacts(tmp_path)
    paths["test_junit"].write_text(
        '<testsuite tests="3" failures="1" errors="0" skipped="1"/>',
        encoding="utf-8",
    )
    errors = manifest._validate_artifacts(paths)
    assert any("failures=1" in error and "skipped=1" in error for error in errors)


def test_release_gate_registry_is_not_release_ready() -> None:
    statuses = manifest._gate_statuses()
    assert set(statuses) == {f"G{number:02d}" for number in range(1, 21)}
    assert any(status != "PASS" for status in statuses.values())
