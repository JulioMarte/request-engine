from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
CERTIFIER = ROOT / "scripts" / "dev" / "certify_push.py"
INSTALLER = ROOT / "scripts" / "dev" / "install_git_hooks.py"
PROFILE = ROOT / "scripts" / "ci" / "local_push_profile.py"
CI_JOBS = ROOT / "scripts" / "ci" / "ci_jobs.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "push-cert@example.invalid")
    _git(root, "config", "user.name", "Push Cert Test")


def test_pre_push_parser_preserves_multiple_refs_and_deletions() -> None:
    certifier = _load(CERTIFIER, "certify_push_parser_test")
    parse = cast(Callable[[str], list[Any]], certifier.parse_push_updates)
    zero = "0" * 40
    payload = (
        f"refs/heads/feature/a {'a' * 40} refs/heads/feature/a {zero}\n"
        f"(delete) {zero} refs/heads/old {'b' * 40}\n"
    )
    updates = parse(payload)
    assert len(updates) == 2
    assert updates[0].local_ref == "refs/heads/feature/a"
    assert updates[0].local_sha == "a" * 40
    assert updates[1].local_sha == zero


def test_certificate_cache_key_changes_with_commit_base_or_toolchain() -> None:
    certifier = _load(CERTIFIER, "certify_push_cache_test")
    cache_key = cast(Callable[[str, str, str], str], certifier._cache_key)
    baseline = cache_key("a" * 40, "b" * 40, "toolchain-a")
    assert cache_key("c" * 40, "b" * 40, "toolchain-a") != baseline
    assert cache_key("a" * 40, "c" * 40, "toolchain-a") != baseline
    assert cache_key("a" * 40, "b" * 40, "toolchain-b") != baseline


def test_cached_pass_requires_exact_commit_base_and_toolchain() -> None:
    certifier = _load(CERTIFIER, "certify_push_cached_pass_test")
    matches = cast(
        Callable[..., bool],
        certifier._certificate_matches,
    )
    certificate: dict[str, object] = {
        "schema_version": "local-push-cert-cache/v1",
        "result": "PASS",
        "commit_sha": "a" * 40,
        "base_sha": "b" * 40,
        "toolchain": "toolchain-a",
    }
    assert matches(
        certificate,
        commit_sha="a" * 40,
        base_sha="b" * 40,
        toolchain="toolchain-a",
    )
    assert not matches(
        certificate,
        commit_sha="a" * 40,
        base_sha="c" * 40,
        toolchain="toolchain-a",
    )


def test_detached_worktree_certifies_commit_not_dirty_working_tree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    source = tmp_path / "value.txt"
    source.write_text("committed\n", encoding="utf-8")
    _git(tmp_path, "add", "value.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    commit_sha = _git(tmp_path, "rev-parse", "HEAD")
    source.write_text("dirty and not part of the push\n", encoding="utf-8")

    certifier = _load(CERTIFIER, "certify_push_worktree_test")
    factory = cast(
        Callable[[Path, str], AbstractContextManager[Path]],
        certifier._detached_worktree,
    )
    with factory(tmp_path, commit_sha) as worktree:
        assert (worktree / "value.txt").read_text(encoding="utf-8") == "committed\n"
    assert source.read_text(encoding="utf-8") == "dirty and not part of the push\n"


def test_remote_tracking_development_is_preferred_as_certificate_base(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    _git(tmp_path, "branch", "development")
    _git(tmp_path, "update-ref", "refs/remotes/origin/development", "HEAD")

    certifier = _load(CERTIFIER, "certify_push_base_test")
    resolve = cast(Callable[[Path, str], str], certifier._base_ref_for_remote)
    assert resolve(tmp_path, "origin") == "refs/remotes/origin/development"


def test_missing_development_base_fails_with_fetch_guidance(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "--quiet", "-m", "base")

    certifier = _load(CERTIFIER, "certify_push_missing_base_test")
    resolve = cast(Callable[[Path, str], str], certifier._base_ref_for_remote)
    with pytest.raises(RuntimeError, match=r"git fetch origin development"):
        resolve(tmp_path, "origin")


def test_local_profile_reuses_canonical_python_quality_step_ids() -> None:
    profile = _load(PROFILE, "local_push_profile_test")
    ci_jobs = _load(CI_JOBS, "ci_jobs_for_push_profile_test")
    raw_jobs: Any = ci_jobs.JOBS
    assert isinstance(raw_jobs, dict)
    python_quality: Any = raw_jobs["python-quality"]
    canonical_keys = {str(step.key) for step in python_quality}
    configured = cast(tuple[str, ...], profile.PYTHON_QUALITY_STEPS)
    remote_only = cast(tuple[str, ...], profile.REMOTE_ONLY_PYTHON_QUALITY_STEPS)

    assert set(configured) <= canonical_keys
    assert "architecture" in configured
    assert "unit" in configured
    assert "modules" in configured
    assert "pyright" in configured
    assert "file-budget" in configured
    assert "dependency-audit" not in configured
    assert remote_only == ("dependency-audit",)


def test_hook_installer_copies_stable_hook_and_certifier_idempotently(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    hook_source = tmp_path / ".githooks" / "pre-push"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    certifier_source = tmp_path / "scripts" / "dev" / "certify_push.py"
    certifier_source.parent.mkdir(parents=True)
    certifier_source.write_text("print('managed certifier')\n", encoding="utf-8")

    installer = _load(INSTALLER, "install_git_hooks_test")
    install = cast(Callable[[Path], int], installer.install)
    check = cast(Callable[[Path], int], installer.check)
    managed = cast(Callable[[Path], Path], installer.managed_hooks_path)

    assert install(tmp_path) == 0
    assert install(tmp_path) == 0
    hooks = managed(tmp_path)
    assert (hooks / "pre-push").read_bytes() == hook_source.read_bytes()
    assert (hooks / "certify_push.py").read_bytes() == certifier_source.read_bytes()
    assert _git(tmp_path, "config", "--local", "--get", "core.hooksPath") == str(hooks)

    certifier_source.write_text("print('new certifier')\n", encoding="utf-8")
    assert check(tmp_path) == 1
