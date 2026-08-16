#!/usr/bin/env python3
"""Fail pull requests that change contract-sensitive code without its normative docs."""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT_PATH: Final = REPO_ROOT / "docs" / "architecture" / "documentation-contracts.toml"


@dataclass(frozen=True, slots=True)
class DocumentationRule:
    rule_id: str
    description: str
    triggers: tuple[str, ...]
    required_docs: tuple[str, ...]
    required_docs_mode: str


def _normalize(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(_normalize(path), _normalize(pattern))


def load_rules(path: Path = CONTRACT_PATH) -> tuple[DocumentationRule, ...]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("documentation contract schema_version must be 1")

    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("documentation contract must define at least one [[rules]] entry")

    rules: list[DocumentationRule] = []
    seen_ids: set[str] = set()
    for entry in rules_raw:
        if not isinstance(entry, dict):
            raise ValueError("documentation rule entries must be TOML tables")
        rule_id = str(entry.get("id", "")).strip()
        if not rule_id or rule_id in seen_ids:
            raise ValueError(f"documentation rule id is empty or duplicated: {rule_id!r}")
        seen_ids.add(rule_id)

        description = str(entry.get("description", "")).strip()
        triggers = tuple(_normalize(str(item)) for item in entry.get("triggers", ()))
        required_docs = tuple(_normalize(str(item)) for item in entry.get("required_docs", ()))
        mode = str(entry.get("required_docs_mode", "all")).strip().lower()
        if not description or not triggers or not required_docs:
            raise ValueError(f"documentation rule {rule_id!r} is incomplete")
        if mode not in {"all", "any"}:
            raise ValueError(
                f"documentation rule {rule_id!r} required_docs_mode must be 'all' or 'any'"
            )
        if any(not item for item in (*triggers, *required_docs)):
            raise ValueError(f"documentation rule {rule_id!r} contains an empty path")
        for doc in required_docs:
            if not (REPO_ROOT / doc).is_file():
                raise ValueError(
                    f"documentation rule {rule_id!r} references missing normative doc {doc!r}"
                )
        rules.append(
            DocumentationRule(
                rule_id=rule_id,
                description=description,
                triggers=triggers,
                required_docs=required_docs,
                required_docs_mode=mode,
            )
        )
    return tuple(rules)


def evaluate_changes(
    changed_files: set[str], rules: tuple[DocumentationRule, ...]
) -> tuple[str, ...]:
    normalized = {_normalize(path) for path in changed_files}
    violations: list[str] = []
    for rule in rules:
        impacted = sorted(
            path
            for path in normalized
            if any(_matches(path, pattern) for pattern in rule.triggers)
        )
        if not impacted:
            continue

        changed_docs = [doc for doc in rule.required_docs if doc in normalized]
        satisfied = (
            len(changed_docs) == len(rule.required_docs)
            if rule.required_docs_mode == "all"
            else bool(changed_docs)
        )
        if satisfied:
            continue

        required = ", ".join(rule.required_docs)
        sample = ", ".join(impacted[:6])
        if len(impacted) > 6:
            sample += f", ... (+{len(impacted) - 6})"
        violations.append(
            f"[{rule.rule_id}] {rule.description}: changed {sample}; "
            f"also update {rule.required_docs_mode} required normative docs: {required}"
        )
    return tuple(violations)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _ref_exists(ref: str) -> bool:
    try:
        _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    return True


def ensure_base_available(base: str) -> str:
    if _ref_exists(base):
        return base

    if base.startswith("origin/"):
        remote_ref = base.removeprefix("origin/")
        _git("fetch", "--no-tags", "--depth=1", "origin", remote_ref)
        return "FETCH_HEAD"

    if len(base) == 40 and all(char in "0123456789abcdefABCDEF" for char in base):
        _git("fetch", "--no-tags", "--depth=1", "origin", base)
        return "FETCH_HEAD"

    raise ValueError(f"documentation contract base ref is unavailable: {base}")


def changed_files(base: str, head: str) -> set[str]:
    available_base = ensure_base_available(base)
    output = _git("diff", "--name-only", f"{available_base}...{head}")
    return {_normalize(line) for line in output.splitlines() if line.strip()}


def resolve_base(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env_sha = os.environ.get("DOCUMENTATION_CONTRACT_BASE_SHA", "").strip()
    if env_sha:
        return env_sha
    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base_ref:
        return f"origin/{base_ref}"
    return None


def resolve_head(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_sha = os.environ.get("DOCUMENTATION_CONTRACT_HEAD_SHA", "").strip()
    return env_sha or "HEAD"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base commit/ref for the three-dot change comparison")
    parser.add_argument("--head", help="head commit/ref; defaults to PR head SHA or HEAD")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the contract registry without evaluating a git diff",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rules = load_rules()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"documentation contract invalid: {exc}", file=sys.stderr)
        return 2

    if args.validate_only:
        print(f"documentation contract registry valid ({len(rules)} rules)")
        return 0

    base = resolve_base(args.base)
    if base is None:
        print(
            "documentation contract registry valid; no base ref available, "
            "so change-impact enforcement was not evaluated"
        )
        return 0
    head = resolve_head(args.head)

    try:
        changed = changed_files(base, head)
    except (subprocess.CalledProcessError, ValueError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"documentation contract diff failed: {detail}", file=sys.stderr)
        return 2

    violations = evaluate_changes(changed, rules)
    if violations:
        print("documentation contract violations:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(
        f"documentation contract satisfied for {len(changed)} changed files "
        f"across {len(rules)} rules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
