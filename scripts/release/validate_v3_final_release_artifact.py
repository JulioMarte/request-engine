#!/usr/bin/env python3
"""Validate the Phase 6 G20 final-release proof artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_GATES = {f"G{number:02d}" for number in range(1, 21)}
REQUIRED_EVIDENCE = {
    "schema_fingerprint",
    "catalog_audit",
    "worker_query_plans",
    "queue_query_plans",
    "booking_query_plans",
    "operational_query_plans",
    "public_api_contract",
    "initial_equivalence",
    "test_quality",
    "test_collection",
    "test_junit",
    "concurrency_stability",
    "test_order_independence",
    "mutation_probes",
    "adversarial_failure",
    "candidate_freeze",
    "production_like_bootstrap",
}
EXPECTED_RUNTIME_ROLES = {
    "application_role": "request_engine_app",
    "worker_role": "request_engine_worker",
    "admin_role": "request_engine_admin",
}


def _valid_sha1(value: Any) -> bool:
    return isinstance(value, str) and SHA1_RE.fullmatch(value) is not None


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def validation_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["final-release proof is not a JSON object"]

    if payload.get("schema_version") != 1:
        errors.append("schema_version is not 1")
    if payload.get("proof") != "v3-final-release-proof":
        errors.append("proof identifier is invalid")
    if payload.get("status") != "PASS":
        errors.append("status is not PASS")
    if payload.get("failures") != []:
        errors.append("failures is not empty")

    criteria = payload.get("criteria")
    if (
        not isinstance(criteria, dict)
        or not criteria
        or any(value is not True for value in criteria.values())
    ):
        errors.append("criteria are incomplete or non-PASS")

    source = payload.get("source")
    if not isinstance(source, dict):
        errors.append("source provenance is missing")
    else:
        for field in ("head_sha", "base_sha", "tested_sha", "checkout_sha", "tree_sha"):
            if not _valid_sha1(source.get(field)):
                errors.append(f"source {field} is malformed")
        if source.get("working_tree_dirty") is not False:
            errors.append("source working tree is not clean")

    gate_statuses = payload.get("gate_statuses")
    if not isinstance(gate_statuses, dict) or set(gate_statuses) != EXPECTED_GATES:
        errors.append("gate status inventory is not exactly G01-G20")
    else:
        for gate in sorted(EXPECTED_GATES - {"G20"}):
            if gate_statuses.get(gate) != "PASS":
                errors.append(f"{gate} is not PASS")
        if gate_statuses.get("G20") not in {"MISSING", "PASS"}:
            errors.append("G20 status is neither MISSING nor PASS")

    evidence_inputs = payload.get("evidence_inputs")
    if not isinstance(evidence_inputs, dict) or set(evidence_inputs) != REQUIRED_EVIDENCE:
        errors.append("evidence input inventory is incomplete or contains drift")
    elif any(not _valid_sha256(value) for value in evidence_inputs.values()):
        errors.append("one or more evidence input digests are malformed")

    registry_digests = payload.get("registry_digests")
    if not isinstance(registry_digests, dict) or set(registry_digests) != {
        "invariant_registry_sha256",
        "race_registry_sha256",
        "gate_registry_sha256",
    }:
        errors.append("registry digest inventory is malformed")
    elif any(not _valid_sha256(value) for value in registry_digests.values()):
        errors.append("one or more registry digests are malformed")

    if not _valid_sha256(payload.get("test_inventory_sha256")):
        errors.append("test inventory digest is malformed")
    if not _valid_sha256(payload.get("preflight_sha256")):
        errors.append("preflight digest is malformed")

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime metadata is missing")
    else:
        if runtime.get("postgres_target") != "18":
            errors.append("runtime PostgreSQL target is not 18")
        if not isinstance(runtime.get("python"), str) or not runtime.get("python"):
            errors.append("runtime Python version is missing")
        for field, expected in EXPECTED_RUNTIME_ROLES.items():
            if runtime.get(field) != expected:
                errors.append(f"runtime {field} does not match the release role contract")

    if payload.get("preflight_evidence_status") != "VALID":
        errors.append("preflight evidence status is not VALID")
    if payload.get("preflight_artifact_set_complete") is not True:
        errors.append("preflight artifact set is not complete")
    if payload.get("preflight_missing_artifacts") != []:
        errors.append("preflight reports missing artifacts")
    if payload.get("preflight_validation_errors") != []:
        errors.append("preflight reports validation errors")
    if payload.get("preflight_release_status") != "NOT_READY":
        errors.append("preflight release status must be NOT_READY")
    if payload.get("preflight_release_ready") is not False:
        errors.append("preflight release_ready must be false")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    errors = validation_errors(payload)
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1
    print("G20 final-release proof artifact: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
