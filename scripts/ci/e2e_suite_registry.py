from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

REGISTRY = Path("tests/system_e2e/suites.toml")
POLICIES = frozenset({"pr", "merge", "nightly", "manual"})


def load_registry() -> dict[str, dict[str, object]]:
    data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    suites = data.get("suites")
    if not isinstance(suites, dict):
        raise SystemExit("suite registry is missing [suites.*] entries")
    return suites


def enabled_suites() -> list[str]:
    return [name for name, spec in load_registry().items() if bool(spec.get("enabled", True))]


def selected_suites(policy: str) -> list[str]:
    if policy not in POLICIES:
        available = ", ".join(sorted(POLICIES))
        raise SystemExit(f"unknown E2E selection policy {policy!r}; available: {available}")
    return [
        name
        for name, spec in load_registry().items()
        if bool(spec.get("enabled", True)) and bool(spec.get(policy, False))
    ]


def resolve(name: str) -> dict[str, object]:
    suites = load_registry()
    if name not in suites:
        raise SystemExit(f"unknown E2E suite {name!r}; available: {', '.join(sorted(suites))}")
    spec = dict(suites[name])
    if not bool(spec.get("enabled", True)):
        raise SystemExit(f"E2E suite {name!r} is registered but disabled")
    spec["name"] = name
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Request Engine E2E suites")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("suite")
    select_parser = sub.add_parser("select")
    select_parser.add_argument("policy", choices=sorted(POLICIES))
    args = parser.parse_args()

    if args.command == "list":
        for name in enabled_suites():
            print(name)
        return 0
    if args.command == "select":
        for name in selected_suites(args.policy):
            print(name)
        return 0

    print(json.dumps(resolve(args.suite), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
