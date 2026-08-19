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


def _rows_by_id(
    value: object,
    *,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{label} is not a list")
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            errors.append(f"{label} contains malformed entries")
            continue
        row_id = row["id"]
        if row_id in rows:
            errors.append(f"{label} contains duplicate id {row_id}")
            continue
        rows[row_id] = row
    return rows


def _valid_owners(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(owner, str) and bool(owner) for owner in value)
    )


def validate_adversarial_failure(payload: dict[str, Any]) -> list[str]:
    """Return semantic validation errors for a G18 proof payload."""
    errors: list[str] = []
    if payload.get("status") != "PASS":
        errors.append("adversarial failure proof status is not PASS")
    if payload.get("schema_version") != 1:
        errors.append("adversarial failure proof schema_version is not 1")
    if payload.get("failures") != []:
        errors.append("adversarial failure proof reports failures")
    if payload.get("missing_evidence") != []:
        errors.append("adversarial failure proof reports missing evidence")

    families = _rows_by_id(payload.get("families"), label="families", errors=errors)
    family_ids = set(families)
    if family_ids != REQUIRED_FAMILIES:
        missing = sorted(REQUIRED_FAMILIES - family_ids)
        extra = sorted(family_ids - REQUIRED_FAMILIES)
        if missing:
            errors.append(f"adversarial failure proof missing families: {', '.join(missing)}")
        if extra:
            errors.append(f"adversarial failure proof has unexpected families: {', '.join(extra)}")
    if payload.get("expected_family_count") != len(REQUIRED_FAMILIES):
        errors.append("adversarial failure proof expected_family_count is not 6")
    if payload.get("observed_family_count") != len(families):
        errors.append("adversarial failure proof observed_family_count is inconsistent")
    for family_id, family in families.items():
        if family.get("status") != "PASS":
            errors.append(f"adversarial family {family_id} is not PASS")
        owners = family.get("owners")
        if not _valid_owners(owners):
            errors.append(f"adversarial family {family_id} has no valid owners")
            continue
        if family.get("expected_owner_count") != len(owners):
            errors.append(f"adversarial family {family_id} expected owner count is inconsistent")
        if family.get("observed_owner_count") != len(owners):
            errors.append(f"adversarial family {family_id} is missing owners")
        if family.get("failures") != []:
            errors.append(f"adversarial family {family_id} reports failures")

    races = _rows_by_id(payload.get("races"), label="races", errors=errors)
    race_ids = set(races)
    if race_ids != REQUIRED_RACES:
        missing = sorted(REQUIRED_RACES - race_ids)
        extra = sorted(race_ids - REQUIRED_RACES)
        if missing:
            errors.append(f"adversarial failure proof missing races: {', '.join(missing)}")
        if extra:
            errors.append(f"adversarial failure proof has unexpected races: {', '.join(extra)}")
    if payload.get("expected_race_count") != len(REQUIRED_RACES):
        errors.append("adversarial failure proof expected_race_count is not 29")
    if payload.get("observed_race_count") != len(races):
        errors.append("adversarial failure proof observed_race_count is inconsistent")
    for race_id, race in races.items():
        if race.get("status") != "PASS":
            errors.append(f"adversarial race {race_id} is not PASS")
        owners = race.get("owners")
        selectors = race.get("required_node_selectors")
        if not _valid_owners(owners):
            errors.append(f"adversarial race {race_id} has no valid owners")
        elif race.get("expected_owner_count") != len(owners):
            errors.append(f"adversarial race {race_id} expected owner count is inconsistent")
        elif race.get("observed_owner_count") != len(owners):
            errors.append(f"adversarial race {race_id} is missing owners")
        if (
            not isinstance(selectors, list)
            or not selectors
            or not all(isinstance(node, str) and "::" in node for node in selectors)
        ):
            errors.append(f"adversarial race {race_id} has no valid required pytest nodes")
        else:
            if race.get("expected_node_selector_count") != len(selectors):
                errors.append(
                    f"adversarial race {race_id} expected pytest node count is inconsistent"
                )
            if race.get("observed_node_selector_count") != len(selectors):
                errors.append(f"adversarial race {race_id} is missing required pytest nodes")

    supporting = payload.get("supporting_artifacts")
    if not isinstance(supporting, dict):
        errors.append("adversarial supporting_artifacts is not an object")
    else:
        supporting_ids = set(supporting)
        if supporting_ids != REQUIRED_SUPPORTING:
            missing = sorted(REQUIRED_SUPPORTING - supporting_ids)
            extra = sorted(supporting_ids - REQUIRED_SUPPORTING)
            if missing:
                errors.append(
                    f"adversarial proof missing supporting artifacts: {', '.join(missing)}"
                )
            if extra:
                errors.append(
                    f"adversarial proof has unexpected supporting artifacts: {', '.join(extra)}"
                )
        for name, result in supporting.items():
            if not isinstance(result, dict) or result.get("status") != "PASS":
                errors.append(f"adversarial supporting artifact {name} is not PASS")

    environment = payload.get("environment")
    if not isinstance(environment, dict) or environment.get("postgres_major") != 18:
        errors.append("adversarial failure proof PostgreSQL target is not 18")

    source = payload.get("source")
    if not isinstance(source, dict):
        errors.append("adversarial failure proof source metadata is malformed")
    else:
        for field in ("head_sha", "tested_sha", "checkout_sha", "tree_sha"):
            value = source.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"adversarial failure proof source.{field} is missing")
    return errors
