import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/release/validate_v3_final_initial_equivalence_artifact.py"
)
SPEC = importlib.util.spec_from_file_location("v3_final_initial_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _sha(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _test_ids_sha(test_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(test_ids).encode("utf-8")).hexdigest()


def _schema_payload() -> dict[str, Any]:
    return {
        "format_version": 1,
        "postgres_major": 18,
        "application_schemas": [
            "request_engine",
            "request_read",
            "request_cmd",
            "request_admin",
        ],
        "fingerprint_roles": [
            "request_engine_schema_owner",
            "request_engine_app",
            "request_engine_worker",
            "request_engine_admin",
        ],
        "catalog": {"relations": [{"relation_name": "organizations"}]},
    }


def _behavior(test_ids: list[str]) -> dict[str, Any]:
    return {
        "selector": "ci_jobs:postgres-v3-candidate:v3-tests",
        "test_count": len(test_ids),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "test_ids": test_ids,
        "test_ids_sha256": _test_ids_sha(test_ids),
        "junit_sha256": "a" * 64,
    }


def _runtime_role(parent: str, suffix: str) -> dict[str, Any]:
    return {
        "role_name": f"re_g17_{suffix}",
        "parent_role": parent,
        "attributes": {
            "can_login": True,
            "superuser": False,
            "create_db": False,
            "create_role": False,
            "replication": False,
            "bypass_rls": False,
        },
        "memberships": [parent],
        "status": "PASS",
    }


def _valid_payload() -> dict[str, Any]:
    schema = _schema_payload()
    test_ids = ["tests.db.test_a::test_one", "tests.e2e.test_b::test_two"]
    return {
        "schema_version": 1,
        "proof": "v3-final-initial-equivalence",
        "status": "PASS",
        "head_sha": "1" * 40,
        "initial_database": "request_engine_v3_g17_initial",
        "candidate_freeze": {
            "candidate_source_commit": "4311200a8a9d8dfa18340c0eba5dff0cfdb47803",
            "current_head": "1" * 40,
            "migration_set_sha256": "2" * 64,
            "artifact_sha256": "3" * 64,
        },
        "initial_sql_sha256": "4" * 64,
        "structural": {
            "equivalent": True,
            "candidate": {"sha256": _sha(schema), "payload": copy.deepcopy(schema)},
            "initial": {"sha256": _sha(schema), "payload": copy.deepcopy(schema)},
        },
        "behavioral": {
            "equivalent": True,
            "candidate": _behavior(test_ids),
            "initial": _behavior(test_ids),
        },
        "runtime": {
            "status": "PASS",
            "database": "request_engine_v3_g17_initial",
            "postgresql_major": 18,
            "secrets_redacted": True,
            "artifact_sha256": "5" * 64,
            "runtime_roles": [
                _runtime_role("request_engine_app", "app"),
                _runtime_role("request_engine_worker", "worker"),
                _runtime_role("request_engine_admin", "admin"),
            ],
        },
        "failures": [],
    }


def test_accepts_complete_semantic_equivalence_artifact() -> None:
    assert validator.validation_errors(_valid_payload()) == []


def test_rejects_schema_payload_that_does_not_match_its_digest() -> None:
    payload = _valid_payload()
    payload["structural"]["initial"]["payload"]["catalog"]["relations"] = []

    errors = validator.validation_errors(payload)

    assert "initial fingerprint sha256 does not match its payload" in errors
    assert "candidate and initial fingerprint payloads differ" in errors


def test_rejects_different_behavioral_test_inventory_even_with_valid_hashes() -> None:
    payload = _valid_payload()
    initial = payload["behavioral"]["initial"]
    initial["test_ids"] = ["tests.db.test_a::test_one", "tests.e2e.test_c::test_three"]
    initial["test_ids_sha256"] = _test_ids_sha(initial["test_ids"])

    errors = validator.validation_errors(payload)

    assert "candidate and initial test inventories differ" in errors


def test_rejects_stale_freeze_and_incomplete_runtime_identity_set() -> None:
    payload = _valid_payload()
    payload["candidate_freeze"]["candidate_source_commit"] = "0" * 40
    payload["runtime"]["runtime_roles"].pop()

    errors = validator.validation_errors(payload)

    assert "candidate_freeze source commit is not the frozen post-G19 source" in errors
    assert "runtime must contain exactly three role records" in errors


def test_rejects_shallow_pass_with_missing_structural_and_behavioral_proofs() -> None:
    payload = _valid_payload()
    payload["structural"] = {"equivalent": True}
    payload["behavioral"] = {"equivalent": True}

    errors = validator.validation_errors(payload)

    assert "candidate fingerprint record must be an object" in errors
    assert "initial fingerprint record must be an object" in errors
    assert "candidate behavioral record must be an object" in errors
    assert "initial behavioral record must be an object" in errors
