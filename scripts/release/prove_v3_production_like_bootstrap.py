#!/usr/bin/env python3
"""Compose the Phase 6 G19 production-like bootstrap release proof."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_NODES = {
    "public_vertical": (
        "tests/e2e/test_multi_user_journeys.py::"
        "test_e2e_many_patients_race_for_one_slot_then_capacity_recovers"
    ),
    "queue_workflow": (
        "tests/e2e/test_multi_user_journeys.py::"
        "test_e2e_queue_preserves_fifo_across_many_users_and_replays_call_next"
    ),
    "worker_runtime_boundary": (
        "tests/integration/v3_worker_runtime/test_production_worker_assembly.py::"
        "test_production_worker_assembly_enforces_runtime_role_split"
    ),
    "worker_crash_recovery": (
        "tests/integration/v3_worker_runtime/test_process_crash_recovery.py::"
        "test_sigkill_after_claim_is_recoverable_and_stale_worker_is_fenced"
    ),
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return payload


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _junit_totals(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else list(root)
    suites = [suite for suite in suites if suite.tag.rsplit("}", 1)[-1] == "testsuite"]
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    clean = _load_json(ROOT / ".phase6/v3-production-like-clean-start.json")
    runtime = _load_json(ROOT / ".phase6/v3-production-like-runtime.json")
    collection = _load_json(ROOT / ".phase6/v3-test-collection.json")
    junit_path = ROOT / ".phase6/v3-tests-junit.xml"
    junit = _junit_totals(junit_path)

    node_ids = collection.get("node_ids")
    collected = set(node_ids) if isinstance(node_ids, list) else set()
    node_results = {
        name: {
            "node_id": node_id,
            "status": "PASS" if node_id in collected else "MISSING",
        }
        for name, node_id in REQUIRED_NODES.items()
    }

    runtime_roles = runtime.get("runtime_roles")
    runtime_role_pass = (
        isinstance(runtime_roles, list)
        and len(runtime_roles) == 3
        and all(isinstance(item, dict) and item.get("status") == "PASS" for item in runtime_roles)
    )
    canonical_suite_pass = (
        isinstance(collection.get("node_count"), int)
        and collection.get("status") == "PASS"
        and junit["tests"] == collection["node_count"]
        and junit["tests"] > 0
        and junit["failures"] == 0
        and junit["errors"] == 0
        and junit["skipped"] == 0
    )

    criteria = {
        "clean_database": clean.get("status") == "PASS",
        "postgresql_18": runtime.get("postgresql_major") == 18,
        "release_shaped_runtime_logins": runtime.get("status") == "PASS" and runtime_role_pass,
        "canonical_release_suite": canonical_suite_pass,
        "representative_public_vertical": node_results["public_vertical"]["status"] == "PASS",
        "queue_outbox_workflow": node_results["queue_workflow"]["status"] == "PASS",
        "app_worker_process_separation": node_results["worker_runtime_boundary"]["status"] == "PASS",
        "restart_reclaim_fencing": node_results["worker_crash_recovery"]["status"] == "PASS",
        "secrets_redacted": runtime.get("secrets_redacted") is True,
    }
    failures = [name for name, passed in criteria.items() if not passed]
    checkout_sha = _git("rev-parse", "HEAD")
    payload = {
        "schema_version": 1,
        "proof": "v3-production-like-bootstrap",
        "status": "PASS" if not failures else "FAIL",
        "criteria": [
            {"id": name, "status": "PASS" if passed else "FAIL"}
            for name, passed in criteria.items()
        ],
        "failures": failures,
        "required_nodes": node_results,
        "canonical_suite": {
            **junit,
            "collected_nodes": collection.get("node_count"),
            "status": "PASS" if canonical_suite_pass else "FAIL",
        },
        "runtime": {
            "postgresql_major": runtime.get("postgresql_major"),
            "database": runtime.get("database"),
            "roles": runtime_roles,
            "secrets_redacted": runtime.get("secrets_redacted"),
        },
        "clean_start": clean,
        "source": {
            "head_sha": os.environ.get("PHASE6_HEAD_SHA") or checkout_sha,
            "tested_sha": os.environ.get("PHASE6_TESTED_SHA") or checkout_sha,
            "checkout_sha": checkout_sha,
            "tree_sha": _git("rev-parse", "HEAD^{tree}"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
