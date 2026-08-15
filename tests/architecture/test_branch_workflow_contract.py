from __future__ import annotations

import os


def test_pull_request_targets_canonical_integration_branch() -> None:
    """Prevent feature PRs from bypassing the development integration branch."""

    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    head_ref = os.environ.get("GITHUB_HEAD_REF", "")

    # GITHUB_BASE_REF/GITHUB_HEAD_REF are populated for pull_request workflows.
    # Local runs and non-PR CI should remain unaffected.
    if not base_ref:
        return

    ordinary_integration = base_ref == "development"
    release_promotion = base_ref == "main" and head_ref == "development"

    assert ordinary_integration or release_promotion, (
        "Invalid pull-request topology: ordinary PRs must target 'development'. "
        "The only PR allowed to target 'main' is the release promotion "
        "'development -> main'. "
        f"Observed '{head_ref} -> {base_ref}'."
    )
