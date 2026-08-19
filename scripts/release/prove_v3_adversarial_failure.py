#!/usr/bin/env python3
"""Compose the mandatory Phase 6 G18 adversarial/failure release proof."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RACE_DOC = ROOT / "docs/release/v3-race-matrix.md"

# A release race is not evidenced merely because a file exists. Each row is bound to
# one or more concrete pytest functions that must appear in the canonical PostgreSQL
# collection artifact. Parametrized nodes match their exact function selector plus
# pytest's trailing ``[...]`` case id.
RACE_NODES: dict[str, tuple[str, ...]] = {
    "R01": (
        "tests/integration/v3_booking_commitments/test_capacity_hold_races.py::test_concurrent_conflicting_holds_commit_exactly_one_capacity_owner",
    ),
    "R02": (
        "tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_hold_confirmation_waiting_past_authoritative_expiry_is_rejected",
        "tests/integration/v3_booking_commitments/test_g18_adversarial_race_boundaries.py::test_hold_confirmation_released_before_authoritative_expiry_consumes_hold_once",
    ),
    "R03": (
        "tests/integration/v3_booking_commitments/test_reservation_races.py::test_cancel_and_reschedule_serialize_to_one_reservation_revision",
    ),
    "R04": (
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py::test_accept_wins_semantically_against_premature_expiry",
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py::test_expiry_wins_semantically_once_offer_is_expired",
    ),
    "R05": (
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py::test_accept_and_decline_serialize_to_one_terminal_effect",
    ),
    "R06": (
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py::test_decline_cannot_release_twice_when_expiry_is_due",
    ),
    "R07": (
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_recovery.py::test_two_offer_workers_serialize_to_one_active_offer",
    ),
    "R08": (
        "tests/integration/v3_reservation_lifecycle/test_released_slot_recovery_races.py::test_r08_duplicate_release_consumers_create_one_recovery_chain",
    ),
    "R09": (
        "tests/integration/v3_first_vertical/test_business_and_queue.py::test_concurrent_call_next_never_returns_same_entry",
    ),
    "R10": (
        "tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py::test_request_cancel_same_revision_has_one_winner_and_one_revision_conflict",
    ),
    "R11": (
        "tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py::test_reservation_cancel_vs_reschedule_same_revision_has_one_winner",
    ),
    "R12": (
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r12_claim_vs_claim_has_one_current_owner",
    ),
    "R13": (
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r13_r14_reclaim_fences_every_stale_transition_and_late_renewal",
    ),
    "R14": (
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r13_r14_reclaim_fences_every_stale_transition_and_late_renewal",
    ),
    "R15": (
        "tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py::test_r15_cancel_wins_row_lock_and_claim_cannot_resurrect_action",
        "tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py::test_r15_claim_wins_row_lock_then_cancel_fences_claim_token",
    ),
    "R16": (
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r16_outbox_completion_wins_row_lock_and_prevents_reclaim",
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r16_outbox_reclaim_wins_row_lock_and_fences_stale_completion",
    ),
    "R17": (
        "tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py::test_r17_simultaneous_duplicate_provider_event_ingest_reuses_one_identity",
        "tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py::test_r17_simultaneous_same_provider_identity_with_different_payload_conflicts",
    ),
    "R18": (
        "tests/integration/v3_reservation_lifecycle/test_provider_business_race.py::test_r18_provider_semantic_callback_vs_business_cancellation_serializes_on_reservation",
    ),
    "R19": (
        "tests/integration/v3_first_vertical/test_http_idempotency_failure.py::test_r19_committed_booking_response_lost_then_same_key_retry_replays_one_effect",
    ),
    "R20": (
        "tests/e2e/test_communication_delivery_lease_fence.py::test_exhausted_crash_dead_letter_replay_recovers_without_second_send",
    ),
    "R21": (
        "tests/integration/v3_first_vertical/test_reminder_occurrence_races.py::test_r21_duplicate_reminder_materialization_serializes_to_one_occurrence_graph",
    ),
    "R22": (
        "tests/integration/v3_first_vertical/test_reminder_plan_races.py::test_r22_cancel_reminder_plan_vs_leased_occurrence_has_one_serialized_plan_outcome",
    ),
    "R23": (
        "tests/integration/v3_reservation_lifecycle/test_appointment_manage_authority_race.py::test_appointments_manage_command_first_holds_authority_until_commit",
        "tests/integration/v3_reservation_lifecycle/test_appointment_manage_authority_race.py::test_appointments_manage_revoke_first_blocks_material_command",
    ),
    "R24": (
        "tests/e2e/test_http_tenant_isolation_matrix.py::test_every_public_operation_enforces_tenant_or_party_boundary_without_mutation",
    ),
    "R25": (
        "tests/db/test_v3_cross_tenant_shared_capacity.py::test_simultaneous_cross_tenant_claims_have_exactly_one_winner",
    ),
    "R26": (
        "tests/integration/v3_booking_commitments/test_g18_adversarial_race_boundaries.py::test_direct_booking_vs_foreign_capacity_hold_has_one_owner_in_both_orders",
        "tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_direct_booking_vs_foreign_slot_offer_has_one_capacity_owner_in_both_orders",
    ),
    "R27": (
        "tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_foreign_shared_booking_winning_race_rolls_back_reschedule_completely",
    ),
    "R28": (
        "tests/db/test_v3_cross_tenant_shared_capacity_authority_races.py::test_binding_activation_race_captures_live_commitment",
        "tests/db/test_v3_cross_tenant_shared_capacity_authority_races.py::test_binding_revocation_race_preserves_historical_link",
    ),
    "R29": (
        "tests/db/test_v3_cross_tenant_shared_capacity_lock_topology.py::test_reversed_cross_tenant_multi_root_requests_do_not_deadlock",
        "tests/integration/v3_booking_commitments/test_cross_tenant_shared_capacity_reschedule_race.py::test_simultaneous_cross_tenant_reschedules_acquire_shared_roots_canonically",
    ),
}

RACE_OWNERS: dict[str, tuple[str, ...]] = {
    race_id: tuple(sorted({selector.split("::", 1)[0] for selector in selectors}))
    for race_id, selectors in RACE_NODES.items()
}

FAMILY_OWNERS: dict[str, tuple[str, ...]] = {
    "attack_security": (
        "tests/db/test_v3_tenant_isolation_adversarial.py",
        "tests/db/test_v3_tenant_function_surfaces_adversarial.py",
        "tests/db/test_v3_party_authority_state_adversarial.py",
        "tests/e2e/test_http_security_matrix.py",
        "tests/e2e/test_http_tenant_isolation_matrix.py",
        "tests/integration/v3_first_vertical/test_http_input_adversarial.py",
    ),
    "race_concurrency": tuple(
        sorted({owner for owners in RACE_OWNERS.values() for owner in owners})
    ),
    "crash_recovery": (
        "tests/integration/v3_worker_runtime/test_process_crash_recovery.py",
        "tests/integration/v3_worker_runtime/test_process_crash_recovery_other_families.py",
        "tests/unit/test_worker_runtime_failure_boundaries.py",
        "tests/e2e/test_communication_delivery_lease_fence.py",
        "tests/e2e/test_communication_reconciliation_release.py",
    ),
    "retry_idempotency": (
        "tests/architecture/test_retryable_command_inventory.py",
        "tests/integration/v3_first_vertical/test_http_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_request_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_reservation_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_attendance_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_queue_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_waitlist_idempotency_failure.py",
        "tests/integration/v3_slot_offer_recovery/test_http_slot_offer_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_reminder_idempotency_failure.py",
    ),
    "order_independence": (".phase6/v3-test-order-independence.json",),
    "mutation_probes": (".phase6/v3-mutation-probes.json",),
}

SUPPORTING_ARTIFACTS = {
    "test_collection": ROOT / ".phase6/v3-test-collection.json",
    "test_junit": ROOT / ".phase6/v3-tests-junit.xml",
    "concurrency_stability": ROOT / ".phase6/v3-concurrency-stability.json",
    "test_order_independence": ROOT / ".phase6/v3-test-order-independence.json",
    "mutation_probes": ROOT / ".phase6/v3-mutation-probes.json",
}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _json_status(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return "MISSING", [f"missing artifact: {path.relative_to(ROOT)}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "FAIL", [f"malformed artifact {path.relative_to(ROOT)}: {exc}"]
    if not isinstance(payload, dict):
        return "FAIL", [f"malformed artifact {path.relative_to(ROOT)}: top-level is not object"]
    return (
        ("PASS", [])
        if payload.get("status") == "PASS"
        else ("FAIL", [f"artifact is not PASS: {path.relative_to(ROOT)}"])
    )


def _collection_node_inventory(path: Path) -> tuple[str, set[str], list[str]]:
    status, failures = _json_status(path)
    if status != "PASS":
        return status, set(), failures
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        return "FAIL", set(), [f"malformed collection artifact: {exc}"]
    raw_nodes = payload.get("node_ids")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return "FAIL", set(), ["test collection artifact has no node_ids inventory"]
    if not all(isinstance(node_id, str) and "::" in node_id for node_id in raw_nodes):
        return "FAIL", set(), ["test collection artifact contains invalid node_ids"]
    node_ids = set(raw_nodes)
    if len(node_ids) != len(raw_nodes):
        return "FAIL", node_ids, ["test collection artifact contains duplicate node_ids"]
    if payload.get("node_count") != len(raw_nodes):
        return "FAIL", node_ids, ["test collection node_count does not match node_ids inventory"]
    return "PASS", node_ids, []


def _selector_collected(selector: str, node_ids: set[str]) -> bool:
    return selector in node_ids or any(node_id.startswith(f"{selector}[") for node_id in node_ids)


def _junit_status(path: Path) -> tuple[str, dict[str, int], list[str]]:
    if not path.exists():
        return "MISSING", {}, [f"missing artifact: {path.relative_to(ROOT)}"]
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return "FAIL", {}, [f"malformed JUnit artifact: {exc}"]

    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    count_keys = ("tests", "failures", "errors", "skipped")
    counts = {key: sum(int(suite.attrib.get(key, "0")) for suite in suites) for key in count_keys}
    failures: list[str] = []
    if counts["tests"] <= 0:
        failures.append("JUnit contains zero tests")
    for key in ("failures", "errors", "skipped"):
        if counts[key] != 0:
            failures.append(f"JUnit contains {counts[key]} {key}")
    return ("PASS" if not failures else "FAIL"), counts, failures


def _race_statuses() -> dict[str, str]:
    pattern = re.compile(
        r"^\| (R\d{2}) \|[^\n]*?\| (PASS|PARTIAL|MISSING|BLOCKED) \| [^|]+\|$",
        flags=re.MULTILINE,
    )
    return dict(pattern.findall(RACE_DOC.read_text(encoding="utf-8")))


def _owner_inventory(paths: tuple[str, ...]) -> tuple[list[str], list[str]]:
    observed = [path for path in paths if (ROOT / path).exists()]
    missing = [path for path in paths if not (ROOT / path).exists()]
    return observed, missing


def build_proof() -> dict[str, Any]:
    failures: list[str] = []
    race_statuses = _race_statuses()
    expected_races = [f"R{number:02d}" for number in range(1, 30)]
    missing_races = sorted(set(expected_races) - set(race_statuses))
    unmapped_races = sorted(set(expected_races) - set(RACE_NODES))
    registry_non_pass = sorted(
        race_id for race_id in expected_races if race_statuses.get(race_id) != "PASS"
    )
    if missing_races:
        failures.append(f"race registry missing: {', '.join(missing_races)}")
    if unmapped_races:
        failures.append(f"race evidence mapping missing: {', '.join(unmapped_races)}")

    supporting: dict[str, dict[str, Any]] = {}
    collection_status, collection_nodes, collection_failures = _collection_node_inventory(
        SUPPORTING_ARTIFACTS["test_collection"]
    )
    supporting["test_collection"] = {
        "status": collection_status,
        "node_count": len(collection_nodes),
    }
    failures.extend(collection_failures)

    junit_status, junit_counts, junit_failures = _junit_status(SUPPORTING_ARTIFACTS["test_junit"])
    supporting["test_junit"] = {"status": junit_status, "counts": junit_counts}
    failures.extend(junit_failures)
    for name, path in SUPPORTING_ARTIFACTS.items():
        if name in {"test_collection", "test_junit"}:
            continue
        status, artifact_failures = _json_status(path)
        supporting[name] = {"status": status}
        failures.extend(artifact_failures)

    race_rows: list[dict[str, Any]] = []
    for race_id in expected_races:
        selectors = RACE_NODES.get(race_id, ())
        owners = RACE_OWNERS.get(race_id, ())
        observed_owners, missing_owners = _owner_inventory(owners)
        missing_selectors = [
            selector
            for selector in selectors
            if not _selector_collected(selector, collection_nodes)
        ]
        if missing_owners:
            failures.append(f"{race_id} missing owner(s): {', '.join(missing_owners)}")
        if missing_selectors:
            failures.append(
                f"{race_id} required pytest node(s) not collected: {', '.join(missing_selectors)}"
            )
        status = (
            "PASS"
            if collection_status == "PASS" and not missing_owners and not missing_selectors
            else "FAIL"
        )
        race_rows.append(
            {
                "id": race_id,
                "status": status,
                "registry_status": race_statuses.get(race_id),
                "owners": list(owners),
                "required_node_selectors": list(selectors),
                "expected_owner_count": len(owners),
                "observed_owner_count": len(observed_owners),
                "expected_node_selector_count": len(selectors),
                "observed_node_selector_count": len(selectors) - len(missing_selectors),
            }
        )

    families: list[dict[str, Any]] = []
    junit_families = {
        "race_concurrency",
        "crash_recovery",
        "retry_idempotency",
        "attack_security",
    }
    race_nodes_missing = any(row["status"] != "PASS" for row in race_rows)
    for family_id, owners in FAMILY_OWNERS.items():
        observed, missing = _owner_inventory(owners)
        family_failures = [f"missing owner: {path}" for path in missing]
        if family_id == "race_concurrency" and collection_status != "PASS":
            family_failures.append("canonical PostgreSQL collection artifact is not PASS")
        if family_id == "race_concurrency" and race_nodes_missing:
            family_failures.append("one or more required race pytest nodes are not collected")
        order_status = supporting.get("test_order_independence", {}).get("status")
        if family_id == "order_independence" and order_status != "PASS":
            family_failures.append("order-independence artifact is not PASS")
        mutation_status = supporting.get("mutation_probes", {}).get("status")
        if family_id == "mutation_probes" and mutation_status != "PASS":
            family_failures.append("mutation-probe artifact is not PASS")
        if family_id in junit_families and junit_status != "PASS":
            family_failures.append("canonical PostgreSQL JUnit artifact is not PASS")
        concurrency_status = supporting.get("concurrency_stability", {}).get("status")
        if family_id == "race_concurrency" and concurrency_status != "PASS":
            family_failures.append("concurrency-stability artifact is not PASS")
        failures.extend(f"{family_id}: {message}" for message in family_failures)
        families.append(
            {
                "id": family_id,
                "status": "PASS" if not family_failures else "FAIL",
                "owners": list(owners),
                "expected_owner_count": len(owners),
                "observed_owner_count": len(observed),
                "failures": family_failures,
            }
        )

    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "source": {
            "head_sha": os.environ.get("PHASE6_HEAD_SHA") or _git("rev-parse", "HEAD"),
            "tested_sha": os.environ.get("PHASE6_TESTED_SHA") or _git("rev-parse", "HEAD"),
            "checkout_sha": _git("rev-parse", "HEAD"),
            "tree_sha": _git("rev-parse", "HEAD^{tree}"),
        },
        "environment": {"python": platform.python_version(), "postgres_major": 18},
        "expected_family_count": 6,
        "observed_family_count": len(families),
        "families": families,
        "expected_race_count": 29,
        "observed_race_count": len(race_rows),
        "races": race_rows,
        "registry_non_pass": registry_non_pass,
        "supporting_artifacts": supporting,
        "missing_evidence": sorted(set(missing_races + unmapped_races)),
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proof = build_proof()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"G18 adversarial/failure proof: {proof['status']}")
    if args.require_pass and proof["status"] != "PASS":
        for failure in proof["failures"]:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
