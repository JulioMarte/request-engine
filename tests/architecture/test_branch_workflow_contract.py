from __future__ import annotations

import os
from pathlib import Path

import pytest

INTEGRATION_LANE_PATH = Path(".github/development-integration-lane")


def _validate_pull_request_topology(*, base_ref: str, head_ref: str, lane_owner: str) -> None:
    if not base_ref:
        return

    if base_ref == "main":
        assert head_ref == "development", (
            "Invalid pull-request topology: the only PR allowed to target 'main' is "
            "the release promotion 'development -> main'. "
            f"Observed '{head_ref} -> {base_ref}'."
        )
        return

    assert base_ref == "development", (
        "Invalid pull-request topology: ordinary PRs must target 'development'. "
        f"Observed '{head_ref} -> {base_ref}'."
    )
    assert head_ref not in {"main", "development"}, (
        "Invalid ordinary PR head: development work must use a dedicated work branch, "
        f"not '{head_ref}'."
    )
    assert not head_ref.startswith("tmp/"), (
        "Temporary scratch branches ('tmp/*') must never become ordinary pull requests. "
        "Create/rebuild a durable feature/fix/release branch from the current "
        "'development' HEAD before opening the PR."
    )
    assert lane_owner == head_ref, (
        "Development integration lane mismatch. "
        f"PR head is '{head_ref}', but {INTEGRATION_LANE_PATH} contains "
        f"'{lane_owner or '<empty>'}'. This usually means the branch was started in "
        "parallel with another active PR, or it was not reconciled after another PR "
        "merged into 'development'. Repair the branch before continuing: fetch the "
        "current origin/development, merge/rebase/rebuild onto that integrated state, "
        f"then set {INTEGRATION_LANE_PATH} to exactly '{head_ref}' and rerun CI. "
        "Do not treat sibling feature branches from the same older development snapshot "
        "as independently merge-ready. Finish -> merge -> delete the active branch, "
        "then start the next branch from the new development HEAD."
    )


def test_pull_request_targets_canonical_integration_branch() -> None:
    """Enforce the single development integration lane in pull-request CI."""

    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    head_ref = os.environ.get("GITHUB_HEAD_REF", "")

    # GITHUB_BASE_REF/GITHUB_HEAD_REF are populated for pull_request workflows.
    # Local runs and non-PR CI should remain unaffected.
    if not base_ref:
        return

    lane_owner = INTEGRATION_LANE_PATH.read_text(encoding="utf-8").strip()
    _validate_pull_request_topology(
        base_ref=base_ref,
        head_ref=head_ref,
        lane_owner=lane_owner,
    )


def test_parallel_sibling_branch_receives_actionable_lane_error() -> None:
    with pytest.raises(AssertionError, match="integration lane mismatch"):
        _validate_pull_request_topology(
            base_ref="development",
            head_ref="feature/second-workstream",
            lane_owner="feature/first-workstream",
        )


def test_tmp_branch_cannot_be_promoted_to_pull_request() -> None:
    with pytest.raises(AssertionError, match=r"tmp/\*"):
        _validate_pull_request_topology(
            base_ref="development",
            head_ref="tmp/experimental-reconciliation",
            lane_owner="tmp/experimental-reconciliation",
        )


def test_release_promotion_is_the_only_main_target() -> None:
    _validate_pull_request_topology(
        base_ref="main",
        head_ref="development",
        lane_owner="feature/previous-integration",
    )

    with pytest.raises(AssertionError, match="only PR allowed to target 'main'"):
        _validate_pull_request_topology(
            base_ref="main",
            head_ref="feature/bypass-development",
            lane_owner="feature/bypass-development",
        )
