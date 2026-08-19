#!/usr/bin/env python3
"""Semantic validator for the Phase 6 G19 production-like bootstrap artifact."""

from __future__ import annotations

from typing import Any

REQUIRED_CRITERIA = {
    "clean_database",
    "postgresql_18",
    "release_shaped_runtime_logins",
    "canonical_release_suite",
    "representative_public_vertical",
    "queue_outbox_workflow",
    "app_worker_process_separation",
    "restart_reclaim_fencing",
    "secrets_redacted",
}
REQUIRED_NODES = {
    "public_vertical",
    "queue_workflow",
    "worker_runtime_boundary",
    "worker_crash_recovery",
}
REQUIRED_PARENT_ROLES = {
    "request_engine_app",
    "request_engine_worker",
    "request_engine_admin",
}
EXPECTED_ATTRIBUTES = {
    "can_login": True,
    "superuser": False,
    "create_db": False,
    "create_role": False,
    "replication": False,
    "bypass_rls": False,
}


def validate_production_like_bootstrap(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("G19 proof schema_version is not 1")
    if payload.get("status") != "PASS":
        errors.append("G19 proof status is not PASS")
    if payload.get("failures") != []:
        errors.append("G19 proof reports failures")

    criteria = payload.get("criteria")
    if not isinstance(criteria, list):
        errors.append("G19 criteria are not a list")
    else:
        by_id = {
            row.get("id"): row
            for row in criteria
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        if set(by_id) != REQUIRED_CRITERIA:
            errors.append("G19 criteria inventory is not exact")
        for criterion_id, row in by_id.items():
            if row.get("status") != "PASS":
                errors.append(f"G19 criterion {criterion_id} is not PASS")

    nodes = payload.get("required_nodes")
    if not isinstance(nodes, dict) or set(nodes) != REQUIRED_NODES:
        errors.append("G19 required-node inventory is not exact")
    elif any(
        not isinstance(row, dict)
        or row.get("status") != "PASS"
        or not isinstance(row.get("node_id"), str)
        or "::" not in row["node_id"]
        for row in nodes.values()
    ):
        errors.append("G19 required-node evidence is incomplete")

    suite = payload.get("canonical_suite")
    if not isinstance(suite, dict) or suite.get("status") != "PASS":
        errors.append("G19 canonical suite is not PASS")
    else:
        tests = suite.get("tests")
        collected = suite.get("collected_nodes")
        if not isinstance(tests, int) or tests <= 0 or tests != collected:
            errors.append("G19 canonical suite execution does not equal collection")
        for field in ("failures", "errors", "skipped"):
            if suite.get(field) != 0:
                errors.append(f"G19 canonical suite reports {field}")

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("G19 runtime evidence is malformed")
    else:
        if runtime.get("postgresql_major") != 18:
            errors.append("G19 PostgreSQL major is not 18")
        if runtime.get("secrets_redacted") is not True:
            errors.append("G19 runtime evidence does not attest secret redaction")
        roles = runtime.get("roles")
        if not isinstance(roles, list) or len(roles) != 3:
            errors.append("G19 runtime role inventory is not exactly three roles")
        else:
            parents = {
                row.get("parent_role") for row in roles if isinstance(row, dict)
            }
            if parents != REQUIRED_PARENT_ROLES:
                errors.append("G19 runtime parent-role inventory is not exact")
            for row in roles:
                if not isinstance(row, dict):
                    errors.append("G19 runtime role record is malformed")
                    continue
                if row.get("status") != "PASS":
                    errors.append(f"G19 runtime role {row.get('role_name')} is not PASS")
                if row.get("attributes") != EXPECTED_ATTRIBUTES:
                    errors.append(f"G19 runtime role {row.get('role_name')} has unsafe attributes")
                parent = row.get("parent_role")
                if row.get("memberships") != [parent]:
                    errors.append(f"G19 runtime role {row.get('role_name')} has extra memberships")

    clean = payload.get("clean_start")
    if not isinstance(clean, dict) or clean.get("status") != "PASS":
        errors.append("G19 clean-start evidence is not PASS")
    elif clean.get("application_schema_count") != 0 or clean.get("public_base_table_count") != 0:
        errors.append("G19 database was not clean before bootstrap")

    source = payload.get("source")
    if not isinstance(source, dict):
        errors.append("G19 source metadata is malformed")
    else:
        for field in ("head_sha", "tested_sha", "checkout_sha", "tree_sha"):
            value = source.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"G19 source.{field} is missing")
    return errors
