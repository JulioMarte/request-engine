from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/release/validate_v3_candidate_freeze_artifact.py"
SPEC = importlib.util.spec_from_file_location("v3_candidate_freeze_validator", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
validator: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _valid_payload() -> dict[str, Any]:
    migrations = [
        {
            "name": f"{index:03d}-migration-{index}.sql",
            "git_blob_sha1": f"{index:040x}",
            "sha256": f"{index:064x}",
        }
        for index in range(1, 44)
    ]
    return {
        "status": "PASS",
        "format_version": 1,
        "candidate_source_commit": "4311200a8a9d8dfa18340c0eba5dff0cfdb47803",
        "candidate_source_tree": "68b92307d85dca0e30cdcee763e8cf9512fef186",
        "ancestry_evidence": "git-merge-base",
        "current_head": "a" * 40,
        "current_tree": "b" * 40,
        "migration_count": 43,
        "migration_order": [item["name"] for item in migrations],
        "migrations": migrations,
        "migration_set_sha256": "c" * 64,
        "locked_tools": [
            {
                "path": "scripts/db/apply_v3_candidate.sh",
                "git_blob_sha1": "d" * 40,
                "sha256": "e" * 64,
            },
            {
                "path": "scripts/db/v3_schema_fingerprint.py",
                "git_blob_sha1": "f" * 40,
                "sha256": "1" * 64,
            },
        ],
        "lock_file_sha256": "2" * 64,
        "failures": [],
    }


def test_candidate_freeze_validator_accepts_complete_proof_shape() -> None:
    assert validator.validation_errors(_valid_payload()) == []


def test_candidate_freeze_validator_rejects_lying_pass() -> None:
    payload = _valid_payload()
    payload["failures"] = ["candidate drift"]
    payload["migrations"] = payload["migrations"][1:]

    errors = validator.validation_errors(payload)

    assert "failures must be an empty list" in errors
    assert "migrations must contain exactly 43 entries" in errors
    assert "migration_order must exactly equal the emitted migration names" in errors


def test_candidate_freeze_validator_rejects_wrong_provenance_and_digests() -> None:
    payload = _valid_payload()
    payload["candidate_source_commit"] = "0" * 40
    payload["ancestry_evidence"] = "trust-me"
    payload["migration_set_sha256"] = "not-a-sha"
    payload["locked_tools"].pop()

    errors = validator.validation_errors(payload)

    assert "candidate_source_commit does not match the frozen G19 source" in errors
    assert "ancestry_evidence must be git-merge-base or ci-base-sha" in errors
    assert "migration_set_sha256 must be 64 lowercase hex characters" in errors
    assert "locked_tools must contain exactly the apply and fingerprint tools" in errors
