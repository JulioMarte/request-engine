from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

HOOK_NAME = "pre-push"
HOOK_SOURCE = Path(".githooks") / HOOK_NAME
CERTIFIER_SOURCE = Path("scripts") / "dev" / "certify_push.py"
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


def _copy_managed(source: Path, target: Path, *, executable: bool) -> None:
    shutil.copyfile(source, target)
    if executable and os.name != "nt":
        target.chmod(0o755)


def install(root: Path) -> int:
    hook_source = root / HOOK_SOURCE
    certifier_source = root / CERTIFIER_SOURCE
    for source in (hook_source, certifier_source):
        if not source.is_file():
            raise RuntimeError(f"tracked hook dependency is missing: {source}")

    hooks = managed_hooks_path(root)
    hooks.mkdir(parents=True, exist_ok=True)
    _copy_managed(hook_source, hooks / HOOK_NAME, executable=True)
    _copy_managed(certifier_source, hooks / CERTIFIER_SOURCE.name, executable=False)

    _git("config", "--local", "core.hooksPath", str(hooks), cwd=root)
    print(f"[PASS] Request Engine Git hooks installed at {hooks}")
    print("Local commits remain unrestricted; exact-SHA certification runs only before push.")
    return check(root)


def check(root: Path) -> int:
    hooks = managed_hooks_path(root)
    hook_source = root / HOOK_SOURCE
    certifier_source = root / CERTIFIER_SOURCE
    managed_hook = hooks / HOOK_NAME
    managed_certifier = hooks / CERTIFIER_SOURCE.name
    configured = _git(
        "config",
        "--local",
        "--get",
        "core.hooksPath",
        cwd=root,
        check=False,
    ).stdout.strip()

    failures: list[str] = []
    expected = (
        (hook_source, managed_hook, "managed pre-push hook"),
        (certifier_source, managed_certifier, "managed push certifier"),
    )
    for source, target, label in expected:
        if not source.is_file():
            failures.append(f"tracked source missing: {source}")
            continue
        if not target.is_file():
            failures.append(f"{label} missing: {target}")
            continue
        if _digest(source) != _digest(target):
            failures.append(f"{label} differs from its tracked source")

    if configured != str(hooks):
        failures.append(f"core.hooksPath is {configured or '<unset>'}; expected {hooks}")
    if managed_hook.is_file() and os.name != "nt" and not os.access(managed_hook, os.X_OK):
        failures.append("managed pre-push hook is not executable")

    if failures:
        print("[LOCAL_PUSH_CERT] Hook installation is not healthy:")
        for failure in failures:
            print(f"- {failure}")
        print("Run: uv run python scripts/dev/install_git_hooks.py")
        return 1

    print(f"[PASS] Request Engine pre-push hook is installed and current: {managed_hook}")
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
