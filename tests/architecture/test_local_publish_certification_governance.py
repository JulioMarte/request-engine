from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_AGENTS = ROOT / "AGENTS.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
POLICY = ROOT / "docs" / "engineering-quality" / "local-publish-certification.md"
HOOK = ROOT / ".githooks" / "pre-push"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_local_agents_may_commit_freely_but_must_not_bypass_publication_gate() -> None:
    instructions = ROOT_AGENTS.read_text(encoding="utf-8")
    assert "Local commits are checkpoints" in instructions
    assert "incomplete or red" in instructions
    assert "pre-push" in instructions
    assert "exact commit SHA" in instructions
    assert "git push --no-verify" in instructions
    assert "MUST NOT cause remote CI lanes to be skipped" in instructions


def test_contributor_workflow_distinguishes_commit_push_and_merge_authority() -> None:
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    assert "Local commits are cheap checkpoints" in contributing
    assert "detached temporary worktree" in contributing
    assert "LOCAL_PUSH_CERTIFIED" in contributing
    assert "GitHub exact-head CI is still authoritative" in contributing
    assert "PostgreSQL" in contributing


def test_hook_is_thin_and_uses_managed_certifier_not_working_tree_policy() -> None:
    hook = HOOK.read_text(encoding="utf-8")
    assert "certify_push.py" in hook
    assert "hook_dir" in hook
    assert "repo_root/scripts/dev/certify_push.py" not in hook
    for duplicated_command in ("ruff", "pyright", "pytest", "tests/architecture"):
        assert duplicated_command not in hook


def test_policy_requires_exact_sha_cache_key_and_preserves_remote_ci() -> None:
    policy = POLICY.read_text(encoding="utf-8")
    for protected_concept in (
        "temporary detached Git worktree",
        "commit SHA",
        "base SHA",
        "toolchain",
        "CACHED PASS",
        "GitHub exact-head CI",
        "GitHub-only agents",
        "--no-verify",
    ):
        assert protected_concept in policy


def test_remote_pull_request_ci_remains_full_authoritative_backstop() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "Python quality and architecture" in workflow
    assert "PostgreSQL 18 current product proof" in workflow
    assert "bash scripts/ci/run_current_product.sh" in workflow
    assert "Observability runtime contract" in workflow
    assert "postgres-production-head" in workflow
    assert "PostgreSQL 18 frozen V3 compatibility" not in workflow
    assert "run_v3_frozen_compatibility.sh" not in workflow
