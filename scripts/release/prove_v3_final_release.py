#!/usr/bin/env python3
"""Compose the Phase 6 G20 exact-head final-release proof from a preflight manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
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
REGISTRY_DIGEST_KEYS = {
    "invariant_registry_sha256",
    "race_registry_sha256",
    "gate_registry_sha256",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return payload


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    preflight = _load_json(args.preflight)
    failures: list[str] = []

    artifact_validation = preflight.get("artifact_validation")
    evidence_inputs: dict[str, str] = {}
    if not isinstance(artifact_validation, dict):
        failures.append("artifact_validation is missing from preflight")
    else:
        for name in sorted(REQUIRED_EVIDENCE):
            record = artifact_validation.get(name)
            if not isinstance(record, dict) or record.get("status") != "PASS":
                failures.append(f"required evidence {name} is not PASS")
                continue
            digest = record.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                failures.append(f"required evidence {name} digest is malformed")
                continue
            evidence_inputs[name] = digest

    registries = preflight.get("registries")
    gate_statuses = registries.get("gate_statuses") if isinstance(registries, dict) else None
    if not isinstance(gate_statuses, dict) or set(gate_statuses) != EXPECTED_GATES:
        failures.append("gate status inventory is not exactly G01-G20")
        gate_statuses = {}
    else:
        for gate in sorted(EXPECTED_GATES - {"G20"}):
            if gate_statuses.get(gate) != "PASS":
                failures.append(f"{gate} is not PASS")
        if gate_statuses.get("G20") not in {"MISSING", "PASS"}:
            failures.append("G20 is neither MISSING nor PASS")

    source = preflight.get("source")
    checkout_sha = _git("rev-parse", "HEAD")
    tree_sha = _git("rev-parse", "HEAD^{tree}")
    expected_head_sha = os.environ.get("PHASE6_HEAD_SHA") or checkout_sha
    expected_tested_sha = os.environ.get("PHASE6_TESTED_SHA") or checkout_sha
    expected_source = {
        "head_sha": expected_head_sha,
        "tested_sha": expected_tested_sha,
        "checkout_sha": checkout_sha,
        "tree_sha": tree_sha,
        "working_tree_dirty": False,
    }
    if not isinstance(source, dict):
        failures.append("source provenance is missing from preflight")
        source = {}
    for field, expected in expected_source.items():
        if source.get(field) != expected:
            failures.append(f"source {field} does not match exact-head execution context")

    runtime = preflight.get("runtime")
    if not isinstance(runtime, dict):
        failures.append("runtime metadata is missing")
        runtime = {}
    if runtime.get("postgres_target") != "18":
        failures.append("PostgreSQL target is not 18")
    for field, expected in {
        "application_role": "request_engine_app",
        "worker_role": "request_engine_worker",
        "admin_role": "request_engine_admin",
    }.items():
        if runtime.get(field) != expected:
            failures.append(f"runtime {field} does not match release role contract")

    artifacts = preflight.get("artifacts")
    registry_digests: dict[str, str] = {}
    if not isinstance(artifacts, dict):
        failures.append("artifact digest map is missing")
    else:
        for key in sorted(REGISTRY_DIGEST_KEYS):
            digest = artifacts.get(key)
            if not isinstance(digest, str) or len(digest) != 64:
                failures.append(f"{key} is malformed")
            else:
                registry_digests[key] = digest

    criteria = {
        "evidence_valid": preflight.get("evidence_status") == "VALID",
        "artifact_set_complete": preflight.get("artifact_set_complete") is True,
        "no_missing_artifacts": preflight.get("missing_artifacts") == [],
        "no_validation_errors": preflight.get("validation_errors") == [],
        "preflight_not_ready": (
            preflight.get("release_status") == "NOT_READY" and preflight.get("release_ready") is False
        ),
        "all_underlying_evidence_bound": len(evidence_inputs) == len(REQUIRED_EVIDENCE),
        "all_pre_g20_gates_pass": all(
            gate_statuses.get(gate) == "PASS" for gate in EXPECTED_GATES - {"G20"}
        ),
        "g20_not_self_proving": gate_statuses.get("G20") in {"MISSING", "PASS"},
        "exact_head_provenance": all(source.get(k) == v for k, v in expected_source.items()),
        "runtime_contract": (
            runtime.get("postgres_target") == "18"
            and runtime.get("application_role") == "request_engine_app"
            and runtime.get("worker_role") == "request_engine_worker"
            and runtime.get("admin_role") == "request_engine_admin"
        ),
        "registry_digests_bound": len(registry_digests) == len(REGISTRY_DIGEST_KEYS),
    }
    failures.extend(name for name, passed in criteria.items() if not passed and name not in failures)

    payload = {
        "schema_version": 1,
        "proof": "v3-final-release-proof",
        "status": "PASS" if not failures else "FAIL",
        "criteria": criteria,
        "failures": failures,
        "source": expected_source,
        "gate_statuses": gate_statuses,
        "evidence_inputs": evidence_inputs,
        "registry_digests": registry_digests,
        "test_inventory_sha256": _canonical_sha256(preflight.get("tests")),
        "runtime": runtime,
        "preflight_sha256": _sha256(args.preflight),
        "preflight_evidence_status": preflight.get("evidence_status"),
        "preflight_artifact_set_complete": preflight.get("artifact_set_complete"),
        "preflight_missing_artifacts": preflight.get("missing_artifacts"),
        "preflight_validation_errors": preflight.get("validation_errors"),
        "preflight_release_status": preflight.get("release_status"),
        "preflight_release_ready": preflight.get("release_ready"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
