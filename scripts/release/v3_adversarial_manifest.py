"""Semantic validation for the Phase 6 G18 adversarial failure artifact."""

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
REQUIRED_SUPPORTING_ARTIFACTS = {
    "test_collection",
    "test_junit",
    "concurrency_stability",
    "test_order_independence",
    "mutation_probes",
}


def _indexed_rows(value: object, *, label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{label} is not a list")
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append(f"{label} contains a malformed row")
            continue
        row_id = item["id"]
        if row_id in rows:
            errors.append(f"{label} contains duplicate id {row_id}")
            continue
        rows[row_id] = item
    return rows


def validate_adversarial_failure(payload: dict[str, Any]) -> list[str]:
    """Reject any G18 artifact that is not structurally and semantically complete."""

    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("G18 schema_version is not 1")
    if payload.get("status") != "PASS":
        errors.append("G18 status is not PASS")
    if payload.get("failures") != []:
        errors.append("G18 artifact reports failures")
    if payload.get("missing_evidence") != []:
        errors.append("G18 artifact reports missing evidence")

    if payload.get("expected_family_count") != len(REQUIRED_FAMILIES):
        errors.append("G18 expected_family_count is not 6")
    if payload.get("observed_family_count") != len(REQUIRED_FAMILIES):
        errors.append("G18 observed_family_count is not 6")
    families = _indexed_rows(payload.get("families"), label="G18 families", errors=errors)
    if set(families) != REQUIRED_FAMILIES:
        errors.append("G18 family inventory does not match the required six families")
    for family_id, row in families.items():
        if row.get("status") != "PASS":
            errors.append(f"G18 family {family_id} is not PASS")
        if row.get("failures") != []:
            errors.append(f"G18 family {family_id} reports failures")
        expected = row.get("expected_owner_count")
        observed = row.get("observed_owner_count")
        owners = row.get("owners")
        if not isinstance(expected, int) or expected <= 0:
            errors.append(f"G18 family {family_id} expected owner count is invalid")
        if observed != expected:
            errors.append(f"G18 family {family_id} owner inventory is incomplete")
        if not isinstance(owners, list) or len(owners) != expected:
            errors.append(f"G18 family {family_id} owner list is malformed")

    if payload.get("expected_race_count") != len(REQUIRED_RACES):
        errors.append("G18 expected_race_count is not 29")
    if payload.get("observed_race_count") != len(REQUIRED_RACES):
        errors.append("G18 observed_race_count is not 29")
    races = _indexed_rows(payload.get("races"), label="G18 races", errors=errors)
    if set(races) != REQUIRED_RACES:
        errors.append("G18 race inventory does not match R01-R29")
    for race_id, row in races.items():
        if row.get("status") != "PASS":
            errors.append(f"G18 race {race_id} is not PASS")
        expected_owners = row.get("expected_owner_count")
        observed_owners = row.get("observed_owner_count")
        owners = row.get("owners")
        if not isinstance(expected_owners, int) or expected_owners <= 0:
            errors.append(f"G18 race {race_id} expected owner count is invalid")
        if observed_owners != expected_owners:
            errors.append(f"G18 race {race_id} owner inventory is incomplete")
        if not isinstance(owners, list) or len(owners) != expected_owners:
            errors.append(f"G18 race {race_id} owner list is malformed")

        expected_nodes = row.get("expected_node_selector_count")
        observed_nodes = row.get("observed_node_selector_count")
        selectors = row.get("required_node_selectors")
        if not isinstance(expected_nodes, int) or expected_nodes <= 0:
            errors.append(f"G18 race {race_id} expected node selector count is invalid")
        if observed_nodes != expected_nodes:
            errors.append(f"G18 race {race_id} pytest node inventory is incomplete")
        if not isinstance(selectors, list) or len(selectors) != expected_nodes:
            errors.append(f"G18 race {race_id} pytest node selector list is malformed")
        elif any(not isinstance(selector, str) or "::" not in selector for selector in selectors):
            errors.append(f"G18 race {race_id} contains malformed pytest node selectors")

    supporting = payload.get("supporting_artifacts")
    if not isinstance(supporting, dict):
        errors.append("G18 supporting_artifacts is not an object")
    else:
        if set(supporting) != REQUIRED_SUPPORTING_ARTIFACTS:
            errors.append("G18 supporting artifact inventory is incomplete")
        for name, evidence in supporting.items():
            if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
                errors.append(f"G18 supporting artifact {name} is not PASS")

    environment = payload.get("environment")
    if not isinstance(environment, dict) or environment.get("postgres_major") != 18:
        errors.append("G18 environment does not prove PostgreSQL 18")

    source = payload.get("source")
    required_source_fields = {"head_sha", "tested_sha", "checkout_sha", "tree_sha"}
    if not isinstance(source, dict):
        errors.append("G18 source metadata is malformed")
    elif any(not isinstance(source.get(field), str) or not source[field] for field in required_source_fields):
        errors.append("G18 source metadata is incomplete")

    return errors
