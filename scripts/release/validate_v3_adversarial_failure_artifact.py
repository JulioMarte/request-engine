#!/usr/bin/env python3
"""Semantic validator for the Phase 6 G18 adversarial failure artifact."""

from __future__ import annotations

from typing import Any

REQUIRED_FAMILIES = {
    "attack_security",
    "race_concurrency",
    "crash_recovery",
    "retry_idempotency",
    "order_independence",
    "mutation_probes",
}
REQUIRED_RACES = {f"R{number:02d}" for number in range(1, 30)}
REQUIRED_SUPPORTING = {
    "test_collection",
    "test_junit",
    "concurrency_stability",
    "test_order_independence",
    "mutation_probes",
}


def _rows_by_id(value: object, *, key: str, label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{label} is not a list")
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get(key), str):
            errors.append(f"{label} contains malformed entries")
            continue
        row_id = row[key]
        if row_id in rows:
            errors.append(f"{label} contains duplicate id {row_id}")
            continue
        rows[row_id] = row
    return rows


def validate_adversarial_failure(payload: dict[str, Any]) -> list[str]:
    """Return semantic validation errors for a G18 proof payload."""
    errors: list[str] = []
    if payload.get("status") != "PASS":
        errors.append("adversarial failure proof status is not PASS")
    if payload.get("schema_version") != 1:
        errors.append("adversarial failure proof schema_version is not 1")
    if payload.get("failures") != []:
        errors.append("adversarial failure proof reports failures")

    families = _rows_by_id(payload.get("families"), key="family_id", label="families", errors=errors)
    family_ids = set(families)
    if family_ids != REQUIRED_FAMILIES:
        missing = sorted(REQUIRED_FAMILIES - family_ids)
        extra = sorted(family_ids - REQUIRED_FAMILIES)
        if missing:
            errors.append(f"adversarial failure proof missing families: {', '.join(missing)}")
        if extra:
            errors.append(f"adversarial failure proof has unexpected families: {', '.join(extra)}")
    for family_id, family in families.items():
        if family.get("status") != "PASS":
            errors.append(f"adversarial family {family_id} is not PASS")
        owners = family.get("owners")
        if not isinstance(owners, list) or not owners or not all(isinstance(owner, str) for owner in owners):
            errors.append(f"adversarial family {family_id} has no valid owners")

    races = _rows_by_id(payload.get("races"), key="race_id", label="races", errors=errors)
    race_ids = set(races)
    if race_ids != REQUIRED_RACES:
        missing = sorted(REQUIRED_RACES - race_ids)
        extra = sorted(race_ids - REQUIRED_RACES)
        if missing:
            errors.append(f"adversarial failure proof missing races: {', '.join(missing)}")
        if extra:
            errors.append(f"adversarial failure proof has unexpected races: {', '.join(extra)}")
    for race_id, race in races.items():
        if race.get("status") != "PASS":
            errors.append(f"adversarial race {race_id} is not PASS")
        if race.get("registry_status") != "PASS":
            errors.append(f"adversarial race {race_id} registry status is not PASS")
        owners = race.get("owners")
        required_nodes = race.get("required_nodes")
        missing_nodes = race.get("missing_nodes")
        if not isinstance(owners, list) or not owners or not all(isinstance(owner, str) for owner in owners):
            errors.append(f"adversarial race {race_id} has no valid owners")
        if (
            not isinstance(required_nodes, list)
            or not required_nodes
            or not all(isinstance(node, str) and "::" in node for node in required_nodes)
        ):
            errors.append(f"adversarial race {race_id} has no valid required pytest nodes")
        if missing_nodes != []:
            errors.append(f"adversarial race {race_id} reports missing pytest nodes")

    supporting = payload.get("supporting_artifacts")
    if not isinstance(supporting, dict):
        errors.append("adversarial supporting_artifacts is not an object")
    else:
        supporting_ids = set(supporting)
        if supporting_ids != REQUIRED_SUPPORTING:
            missing = sorted(REQUIRED_SUPPORTING - supporting_ids)
            extra = sorted(supporting_ids - REQUIRED_SUPPORTING)
            if missing:
                errors.append(f"adversarial proof missing supporting artifacts: {', '.join(missing)}")
            if extra:
                errors.append(f"adversarial proof has unexpected supporting artifacts: {', '.join(extra)}")
        for name, result in supporting.items():
            if not isinstance(result, dict) or result.get("status") != "PASS":
                errors.append(f"adversarial supporting artifact {name} is not PASS")

    source = payload.get("source")
    if not isinstance(source, dict):
        errors.append("adversarial failure proof source metadata is malformed")
    else:
        for field in ("head_sha", "tested_sha", "checkout_sha", "tree_sha"):
            value = source.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"adversarial failure proof source.{field} is missing")
    return errors
