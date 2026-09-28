"""Run the adversarial pilot-readiness matrix locally.

This intentionally runs each matrix case in its own pytest process, matching
the GitHub workflows and making the first failing case easy to identify.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

READINESS_PROBES = (
    "tests/adversarial/test_pilot_readiness_contract.py::"
    "test_party_identity_has_first_class_duplicate_resolution_capability",
    "tests/adversarial/test_pilot_readiness_contract.py::"
    "test_walk_in_queue_can_persist_preferred_resource",
    "tests/adversarial/test_contextual_reschedule_readiness.py::"
    "test_public_reschedule_accepts_contextual_appointment_option",
)

POSTGRES_CHALLENGES = (
    "tests/e2e/test_onboarding_journey.py::"
    "test_newly_provisioned_organization_becomes_operational_through_http",
    "tests/e2e/test_discovery_shared_capacity_race.py::"
    "test_discovery_shared_capacity_race_has_one_opaque_winner",
    "tests/e2e/test_f6_mutation_concurrency_matrix.py::"
    "test_f6_concurrent_recovery_proposal_and_execution_replay_once",
    "tests/integration/f1_operational_profile/"
    "test_contextual_booking_additional_races.py::"
    "test_resource_wide_exception_serializes_before_book_and_makes_option_stale",
    "tests/integration/f1_operational_profile/"
    "test_adversarial_multilocation_capacity.py::"
    "test_same_resource_can_be_assigned_to_two_locations_but_cannot_be_oversold",
    "tests/e2e/test_adversarial_cross_principal_intake_race.py::"
    "test_admin_and_bot_compete_through_one_owner_without_last_write_wins",
    "tests/integration/f1_operational_profile/"
    "test_multi_resource_commercial_provenance.py::"
    "test_multi_resource_booking_preserves_every_contextual_commercial_source",
    "tests/integration/f1_operational_profile/"
    "test_adversarial_dental_resource_contention.py::"
    "test_two_dentists_cannot_double_book_one_chair_and_one_assistant",
)


def _run(command: Sequence[str], *, env: dict[str, str]) -> int:
    print(f"\n==> {' '.join(command)}", flush=True)
    return subprocess.run(command, env=env, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="run only the probes that do not require PostgreSQL",
    )
    parser.add_argument(
        "--postgres-only",
        action="store_true",
        help="run migration plus PostgreSQL-backed challenges",
    )
    args = parser.parse_args()
    if args.readiness_only and args.postgres_only:
        parser.error("--readiness-only and --postgres-only are mutually exclusive")

    env = os.environ.copy()
    env.setdefault("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "x" * 64)
    failures: list[str] = []

    if not args.postgres_only:
        for nodeid in READINESS_PROBES:
            if _run(("uv", "run", "pytest", nodeid, "-q", "--tb=short"), env=env):
                failures.append(nodeid)

    if not args.readiness_only:
        if _run(("uv", "run", "alembic", "upgrade", "head"), env=env):
            failures.append("alembic upgrade head")
        else:
            for nodeid in POSTGRES_CHALLENGES:
                command = ("uv", "run", "pytest", nodeid, "-q", "-m", "postgres", "--tb=short")
                if _run(command, env=env):
                    failures.append(nodeid)

    if failures:
        print("\nFAILED CASES:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("\nAll selected adversarial pilot-readiness cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
