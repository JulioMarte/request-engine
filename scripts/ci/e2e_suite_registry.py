from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from io import BufferedWriter, TextIOWrapper
from pathlib import Path
from typing import cast

REGISTRY = Path("tests/system_e2e/suites.toml")
POLICIES = frozenset({"pr", "merge", "nightly", "manual"})
DRIVERS = frozenset({"generic", "network-boundary"})
NETWORK_BOUNDARY_SERVICES = frozenset({"api", "api-replica", "control-plane"})
NETWORK_BOUNDARY_INGRESS = frozenset({"api-ingress", "control-ingress"})
NETWORK_BOUNDARY_TLS_HOSTS = frozenset({"api-lab", "api-replica-lab", "control-lab"})
INFRASTRUCTURE_SERVICES = frozenset({"event-sink", "mailpit", "openbao", "smtp-provider"})


def _string_set(spec: dict[str, object], field: str, name: str) -> set[str]:
    value = spec.get(field, [])
    if not isinstance(value, list):
        raise SystemExit(f"suite {name!r} has invalid {field}; expected a string list")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise SystemExit(f"suite {name!r} has invalid {field}; expected a string list")
    return set(cast(list[str], items))


def _validate_driver(name: str, spec: dict[str, object]) -> None:
    driver = spec.get("driver", "generic")
    if not isinstance(driver, str) or driver not in DRIVERS:
        raise SystemExit(f"suite {name!r} declares unsupported driver {driver!r}")
    ingress = _string_set(spec, "ingress_services", name)
    tls_hosts = _string_set(spec, "tls_hosts", name)
    infrastructure = _string_set(spec, "infrastructure_services", name)
    profiles = _string_set(spec, "profiles", name)
    services = _string_set(spec, "services", name)
    if infrastructure - INFRASTRUCTURE_SERVICES:
        raise SystemExit(
            f"suite {name!r} declares unsupported infrastructure services: "
            f"{sorted(infrastructure - INFRASTRUCTURE_SERVICES)}"
        )
    if "smtp-provider" in infrastructure and "smtp-provider" not in profiles:
        raise SystemExit(f"suite {name!r} must enable the smtp-provider profile")
    if "smtp-provider" in profiles and "smtp-provider" not in infrastructure:
        raise SystemExit(f"suite {name!r} must declare smtp-provider as infrastructure")
    if any(not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", host) for host in tls_hosts):
        raise SystemExit(f"suite {name!r} contains an invalid TLS hostname")
    if driver == "generic":
        if ingress:
            raise SystemExit(f"generic suite {name!r} cannot declare ingress services")
        return

    selector = spec.get("selector")
    if (
        name != "network-auth-admission"
        or selector != "network-auth-admission"
        or not services >= NETWORK_BOUNDARY_SERVICES
        or not {"network-lab", "secrets"} <= profiles
        or frozenset(ingress) != NETWORK_BOUNDARY_INGRESS
        or frozenset(tls_hosts) != NETWORK_BOUNDARY_TLS_HOSTS
    ):
        raise SystemExit(f"suite {name!r} does not satisfy the network-boundary driver contract")


def load_registry() -> dict[str, dict[str, object]]:
    data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    suites = data.get("suites")
    if not isinstance(suites, dict):
        raise SystemExit("suite registry is missing [suites.*] entries")
    entries = cast(dict[object, object], suites)
    if any(
        not isinstance(name, str) or not isinstance(spec, dict) for name, spec in entries.items()
    ):
        raise SystemExit("suite registry entries must be named tables")
    validated = cast(dict[str, dict[str, object]], suites)
    for name, spec in validated.items():
        _validate_driver(name, spec)
    return validated


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
    spec["driver"] = spec.get("driver", "generic")
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
    # This CLI is a line-oriented Bash protocol, including on Windows hosts.
    cast("TextIOWrapper[BufferedWriter]", sys.stdout).reconfigure(newline="\n")
    sys.exit(main())
