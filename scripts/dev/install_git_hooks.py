from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

HOOK_NAME = "pre-push"
HOOK_SOURCE = Path(".githooks") / HOOK_NAME
MANAGED_ROOT = Path("request-engine") / "hooks"


def _git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def _repository_root() -> Path:
    return Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _common_git_dir(root: Path) -> Path:
    raw = Path(_git("rev-parse", "--git-common-dir", cwd=root).stdout.strip())
    if raw.is_absolute():
        return raw.resolve()
    return (root / raw).resolve()


def managed_hooks_path(root: Path) -> Path:
    return (_common_git_dir(root) / MANAGED_ROOT).resolve()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(root: Path) -> int:
    source = root / HOOK_SOURCE
    if not source.is_file():
        raise RuntimeError(f"tracked hook template is missing: {source}")

    hooks = managed_hooks_path(root)
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / HOOK_NAME
    shutil.copyfile(source, target)
    if os.name != "nt":
        target.chmod(0o755)

    _git("config", "--local", "core.hooksPath", str(hooks), cwd=root)
    print(f"[PASS] Request Engine Git hooks installed at {hooks}")
    print("Local commits remain unrestricted; exact-SHA certification runs only before push.")
    return check(root)


def check(root: Path) -> int:
    source = root / HOOK_SOURCE
    hooks = managed_hooks_path(root)
    target = hooks / HOOK_NAME
    configured = _git(
        "config",
        "--local",
        "--get",
        "core.hooksPath",
        cwd=root,
        check=False,
    ).stdout.strip()

    failures: list[str] = []
    if not source.is_file():
        failures.append(f"tracked hook template missing: {source}")
    if not target.is_file():
        failures.append(f"managed hook missing: {target}")
    if configured != str(hooks):
        failures.append(f"core.hooksPath is {configured or '<unset>'}; expected {hooks}")
    if source.is_file() and target.is_file() and _digest(source) != _digest(target):
        failures.append("managed pre-push hook differs from the tracked template")
    if target.is_file() and os.name != "nt" and not os.access(target, os.X_OK):
        failures.append("managed pre-push hook is not executable")

    if failures:
        print("[LOCAL_PUSH_CERT] Hook installation is not healthy:")
        for failure in failures:
            print(f"- {failure}")
        print("Run: uv run python scripts/dev/install_git_hooks.py")
        return 1

    print(f"[PASS] Request Engine pre-push hook is installed and current: {target}")
    return 0


def uninstall(root: Path) -> int:
    hooks = managed_hooks_path(root)
    configured = _git(
        "config",
        "--local",
        "--get",
        "core.hooksPath",
        cwd=root,
        check=False,
    ).stdout.strip()
    if configured == str(hooks):
        _git("config", "--local", "--unset", "core.hooksPath", cwd=root, check=False)
    shutil.rmtree(hooks, ignore_errors=True)
    print("[PASS] Request Engine managed Git hook installation removed.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or verify Request Engine repository-managed Git hooks."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--uninstall", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = _repository_root()
    if args.check:
        return check(root)
    if args.uninstall:
        return uninstall(root)
    return install(root)


if __name__ == "__main__":
    raise SystemExit(main())
