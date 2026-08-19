#!/usr/bin/env python3
"""Semantically validate the final V3 initial-equivalence proof artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final

EXPECTED_SOURCE_COMMIT: Final = "4311200a8a9d8dfa18340c0eba5dff0cfdb47803"
EXPECTED_INITIAL_SQL_SHA256: Final = (
    "502c98fcce5b5480a3e8f34804ce3a61495e679811a3ac6d0be4872107c34c88"
)
EXPECTED_SCHEMAS: Final = (
    "request_engine",
    "request_read",
    "request_cmd",
    "request_admin",
)
EXPECTED_FINGERPRINT_ROLES: Final = (
    "request_engine_schema_owner",
    "request_engine_app",
    "request_engine_worker",
    "request_engine_admin",
)
EXPECTED_RUNTIME_PARENTS: Final = {
    "app": "request_engine_app",
    "worker": "request_engine_worker",
    "admin": "request_engine_admin",
}
EXPECTED_SELECTOR: Final = "ci_jobs:postgres-v3-candidate:v3-tests"
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _test_ids_sha256(test_ids: list[str]) -> str:
    encoded = "\n".join(test_ids).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_schema_fingerprint(
    label: str,
    record: object,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        errors.append(f"{label} fingerprint record must be an object")
        return None
    payload = record.get("payload")
    digest = record.get("sha256")
    if not isinstance(payload, dict):
        errors.append(f"{label} fingerprint payload must be an object")
        return None
    if payload.get("format_version") != 1:
        errors.append(f"{label} fingerprint format_version must be 1")
    if payload.get("postgres_major") != 18:
        errors.append(f"{label} fingerprint postgres_major must be 18")
    if payload.get("application_schemas") != list(EXPECTED_SCHEMAS):
        errors.append(f"{label} fingerprint application_schemas are not canonical")
    if payload.get("fingerprint_roles") != list(EXPECTED_FINGERPRINT_ROLES):
        errors.append(f"{label} fingerprint roles are not canonical")
    if not isinstance(payload.get("catalog"), dict) or not payload["catalog"]:
        errors.append(f"{label} fingerprint catalog is empty or malformed")
    if not _valid_sha256(digest):
        errors.append(f"{label} fingerprint sha256 is malformed")
    elif _canonical_sha256(payload) != digest:
        errors.append(f"{label} fingerprint sha256 does not match its payload")
    return payload


def _validate_behavior_record(
    label: str,
    record: object,
    errors: list[str],
) -> list[str] | None:
    if not isinstance(record, dict):
        errors.append(f"{label} behavioral record must be an object")
        return None
    if record.get("selector") != EXPECTED_SELECTOR:
        errors.append(f"{label} behavioral selector is not the canonical V3 suite")
    test_ids = record.get("test_ids")
    if (
        not isinstance(test_ids, list)
        or not test_ids
        or any(not isinstance(item, str) or not item for item in test_ids)
    ):
        errors.append(f"{label} test_ids must be a non-empty list of strings")
        return None
    typed_ids = [str(item) for item in test_ids]
    if typed_ids != sorted(typed_ids):
        errors.append(f"{label} test_ids must be sorted")
    if len(typed_ids) != len(set(typed_ids)):
        errors.append(f"{label} test_ids must be unique")
    if record.get("test_count") != len(typed_ids):
        errors.append(f"{label} test_count does not match test_ids")
    for field in ("failures", "errors", "skipped"):
        if record.get(field) != 0:
            errors.append(f"{label} {field} must be zero")
    test_ids_digest = record.get("test_ids_sha256")
    if not _valid_sha256(test_ids_digest):
        errors.append(f"{label} test_ids_sha256 is malformed")
    elif _test_ids_sha256(typed_ids) != test_ids_digest:
        errors.append(f"{label} test_ids_sha256 does not match test_ids")
    if not _valid_sha256(record.get("junit_sha256")):
        errors.append(f"{label} junit_sha256 is malformed")
    return typed_ids


def _validate_runtime(
    runtime: object,
    initial_database: object,
    errors: list[str],
) -> None:
    if not isinstance(runtime, dict):
        errors.append("runtime must be an object")
        return
    if runtime.get("status") != "PASS":
        errors.append("runtime status must be PASS")
    if not isinstance(initial_database, str) or not initial_database:
        errors.append("initial_database must be a non-empty string")
    elif runtime.get("database") != initial_database:
        errors.append("runtime database does not match initial_database")
    if runtime.get("postgresql_major") != 18:
        errors.append("runtime postgresql_major must be 18")
    if runtime.get("secrets_redacted") is not True:
        errors.append("runtime secrets_redacted must be true")
    if not _valid_sha256(runtime.get("artifact_sha256")):
        errors.append("runtime artifact_sha256 is malformed")

    role_records = runtime.get("runtime_roles")
    if not isinstance(role_records, list) or len(role_records) != 3:
        errors.append("runtime must contain exactly three role records")
        return
    observed_parents: set[str] = set()
    expected_attributes = {
        "can_login": True,
        "superuser": False,
        "create_db": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }
    for index, record in enumerate(role_records):
        if not isinstance(record, dict):
            errors.append(f"runtime role[{index}] must be an object")
            continue
        parent = record.get("parent_role")
        if isinstance(parent, str):
            observed_parents.add(parent)
        if record.get("status") != "PASS":
            errors.append(f"runtime role[{index}] status must be PASS")
        if record.get("attributes") != expected_attributes:
            errors.append(f"runtime role[{index}] attributes are not release-shaped")
        if not isinstance(parent, str) or record.get("memberships") != [parent]:
            errors.append(f"runtime role[{index}] membership is not exactly its parent")
    if observed_parents != set(EXPECTED_RUNTIME_PARENTS.values()):
        errors.append("runtime parent-role inventory is not app/worker/admin")


def validation_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["artifact must be a JSON object"]

    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("proof") != "v3-final-initial-equivalence":
        errors.append("proof identifier is invalid")
    if payload.get("status") != "PASS":
        errors.append("status must be PASS")
    if payload.get("failures") != []:
        errors.append("failures must be an empty list")

    head_sha = payload.get("head_sha")
    if not isinstance(head_sha, str) or HEX40.fullmatch(head_sha) is None:
        errors.append("head_sha must be 40 lowercase hex characters")

    freeze = payload.get("candidate_freeze")
    if not isinstance(freeze, dict):
        errors.append("candidate_freeze must be an object")
    else:
        if freeze.get("candidate_source_commit") != EXPECTED_SOURCE_COMMIT:
            errors.append("candidate_freeze source commit is not the frozen post-G19 source")
        if freeze.get("current_head") != head_sha:
            errors.append("candidate_freeze current_head does not match proof head_sha")
        for field in ("artifact_sha256", "migration_set_sha256"):
            if not _valid_sha256(freeze.get(field)):
                errors.append(f"candidate_freeze {field} is malformed")

    initial_sql_sha256 = payload.get("initial_sql_sha256")
    if not _valid_sha256(initial_sql_sha256):
        errors.append("initial_sql_sha256 is malformed")
    elif initial_sql_sha256 != EXPECTED_INITIAL_SQL_SHA256:
        errors.append("initial_sql_sha256 is not the reviewed V3 0001_initial baseline")

    structural = payload.get("structural")
    if not isinstance(structural, dict):
        errors.append("structural must be an object")
        candidate_payload = None
        initial_payload = None
    else:
        if structural.get("equivalent") is not True:
            errors.append("structural equivalent must be true")
        candidate_payload = _validate_schema_fingerprint(
            "candidate", structural.get("candidate"), errors
        )
        initial_payload = _validate_schema_fingerprint("initial", structural.get("initial"), errors)
        if candidate_payload is not None and initial_payload is not None:
            if candidate_payload != initial_payload:
                errors.append("candidate and initial fingerprint payloads differ")
            candidate_record = structural.get("candidate")
            initial_record = structural.get("initial")
            if (
                isinstance(candidate_record, dict)
                and isinstance(initial_record, dict)
                and candidate_record.get("sha256") != initial_record.get("sha256")
            ):
                errors.append("candidate and initial fingerprint digests differ")

    behavioral = payload.get("behavioral")
    if not isinstance(behavioral, dict):
        errors.append("behavioral must be an object")
    else:
        if behavioral.get("equivalent") is not True:
            errors.append("behavioral equivalent must be true")
        candidate_ids = _validate_behavior_record("candidate", behavioral.get("candidate"), errors)
        initial_ids = _validate_behavior_record("initial", behavioral.get("initial"), errors)
        if candidate_ids is not None and initial_ids is not None and candidate_ids != initial_ids:
            errors.append("candidate and initial test inventories differ")

    _validate_runtime(payload.get("runtime"), payload.get("initial_database"), errors)
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    errors = validation_errors(payload)
    if errors:
        print("V3 final-initial equivalence artifact is INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("V3 final-initial equivalence artifact is VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
