from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

REGISTRY = Path("tests/system_e2e/suites.toml")


def load_registry() -> dict[str, dict[str, object]]:
    data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    suites = data.get("suites")
    if not isinstance(suites, dict):
        raise SystemExit("suite registry is missing [suites.*] entries")
    return suites


def enabled_suites() -> list[str]:
    return [name for name, spec in load_registry().items() if bool(spec.get("enabled", True))]


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
    args = parser.parse_args()

    if args.command == "list":
        for name in enabled_suites():
            print(name)
        return 0

    print(json.dumps(resolve(args.suite), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
