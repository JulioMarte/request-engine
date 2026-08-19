#!/usr/bin/env python3
"""Semantically validate a V3 candidate-freeze proof artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Final

EXPECTED_SOURCE_COMMIT: Final = "4311200a8a9d8dfa18340c0eba5dff0cfdb47803"
EXPECTED_SOURCE_TREE: Final = "68b92307d85dca0e30cdcee763e8cf9512fef186"
EXPECTED_MIGRATION_COUNT: Final = 43
EXPECTED_ANCESTRY_EVIDENCE: Final = {"git-merge-base", "ci-base-sha"}
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


def validation_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["artifact must be a JSON object"]

    if payload.get("format_version") != 1:
        errors.append("format_version must be 1")
    if payload.get("status") != "PASS":
        errors.append("status must be PASS")
    if payload.get("candidate_source_commit") != EXPECTED_SOURCE_COMMIT:
        errors.append("candidate_source_commit does not match the frozen G19 source")
    if payload.get("candidate_source_tree") != EXPECTED_SOURCE_TREE:
        errors.append("candidate_source_tree does not match the frozen G19 source")
    if payload.get("ancestry_evidence") not in EXPECTED_ANCESTRY_EVIDENCE:
        errors.append("ancestry_evidence must be git-merge-base or ci-base-sha")

    failures = payload.get("failures")
    if failures != []:
        errors.append("failures must be an empty list")

    migrations = payload.get("migrations")
    if not isinstance(migrations, list):
        errors.append("migrations must be a list")
        migrations = []
    if payload.get("migration_count") != EXPECTED_MIGRATION_COUNT:
        errors.append(f"migration_count must be {EXPECTED_MIGRATION_COUNT}")
    if len(migrations) != EXPECTED_MIGRATION_COUNT:
        errors.append(f"migrations must contain exactly {EXPECTED_MIGRATION_COUNT} entries")

    order = payload.get("migration_order")
    names = [item.get("name") for item in migrations if isinstance(item, dict)]
    if not isinstance(order, list) or order != names:
        errors.append("migration_order must exactly equal the emitted migration names")
    if len(names) != len(set(names)):
        errors.append("migration names must be unique")

    for index, item in enumerate(migrations):
        if not isinstance(item, dict):
            errors.append(f"migration[{index}] must be an object")
            continue
        name = item.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[0-9]{3}-.+\.sql", name):
            errors.append(f"migration[{index}].name is invalid")
        blob = item.get("git_blob_sha1")
        if not isinstance(blob, str) or HEX40.fullmatch(blob) is None:
            errors.append(f"migration[{index}].git_blob_sha1 must be 40 lowercase hex characters")
        sha256 = item.get("sha256")
        if not isinstance(sha256, str) or HEX64.fullmatch(sha256) is None:
            errors.append(f"migration[{index}].sha256 must be 64 lowercase hex characters")

    if len([item for item in migrations if isinstance(item, dict)]) == EXPECTED_MIGRATION_COUNT:
        blobs = [item.get("git_blob_sha1") for item in migrations]
        if len(blobs) != len(set(blobs)):
            errors.append("migration git blobs must be unique")

    for field in ("migration_set_sha256", "lock_file_sha256"):
        value = payload.get(field)
        if not isinstance(value, str) or HEX64.fullmatch(value) is None:
            errors.append(f"{field} must be 64 lowercase hex characters")

    tools = payload.get("locked_tools")
    if not isinstance(tools, list) or len(tools) != 2:
        errors.append("locked_tools must contain exactly the apply and fingerprint tools")
        tools = []
    expected_tool_paths = {
        "scripts/db/apply_v3_candidate.sh",
        "scripts/db/v3_schema_fingerprint.py",
    }
    observed_tool_paths: set[str] = set()
    for index, item in enumerate(tools):
        if not isinstance(item, dict):
            errors.append(f"locked_tools[{index}] must be an object")
            continue
        path = item.get("path")
        if isinstance(path, str):
            observed_tool_paths.add(path)
        blob = item.get("git_blob_sha1")
        digest = item.get("sha256")
        if not isinstance(blob, str) or HEX40.fullmatch(blob) is None:
            errors.append(f"locked_tools[{index}].git_blob_sha1 is invalid")
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            errors.append(f"locked_tools[{index}].sha256 is invalid")
    if observed_tool_paths != expected_tool_paths:
        errors.append("locked_tools inventory is not the exact expected set")

    for field in ("current_head", "current_tree"):
        value = payload.get(field)
        if not isinstance(value, str) or HEX40.fullmatch(value) is None:
            errors.append(f"{field} must be 40 lowercase hex characters")

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
        print("V3 candidate freeze artifact is INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("V3 candidate freeze artifact is VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
