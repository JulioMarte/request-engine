#!/usr/bin/env python3
"""Measure exact declared TCP listeners from one deployment vantage point."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
import socket
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


class NetworkProbeError(ValueError):
    pass


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise NetworkProbeError("unsupported network plan")
    config = cast(dict[str, Any], plan)
    if config.get("schema") != "request-engine/network-plan/v1":
        raise NetworkProbeError("unsupported network plan")
    for name in ("candidate", "configuration_reference", "source_reference"):
        value = config.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise NetworkProbeError(f"{name} must be a bounded nonempty reference")
    if config.get("vantage") not in {"public", "private"}:
        raise NetworkProbeError("vantage must be public or private")
    timeout = config.get("timeout_seconds", 3)
    if type(timeout) not in {int, float}:
        raise NetworkProbeError("timeout must be finite and between 0.1 and 10 seconds")
    try:
        finite = math.isfinite(timeout)
    except OverflowError:
        finite = False
    if not finite or not 0.1 <= timeout <= 10:
        raise NetworkProbeError("timeout must be finite and between 0.1 and 10 seconds")
    endpoints = config.get("endpoints")
    if not isinstance(endpoints, list):
        raise NetworkProbeError("declare between 1 and 64 exact endpoints")
    endpoints = cast(list[Any], endpoints)
    if not 1 <= len(endpoints) <= 64:
        raise NetworkProbeError("declare between 1 and 64 exact endpoints")
    identifiers: set[str] = set()
    for endpoint in endpoints:
        _validate_endpoint(endpoint, identifiers)
    return config


def _validate_endpoint(endpoint: Any, identifiers: set[str]) -> None:
    if not isinstance(endpoint, dict):
        raise NetworkProbeError("endpoint must be an object")
    endpoint = cast(dict[str, Any], endpoint)
    identifier = endpoint.get("id")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
        raise NetworkProbeError("endpoint id must be bounded and nonempty")
    if identifier in identifiers:
        raise NetworkProbeError("duplicate endpoint id")
    identifiers.add(identifier)
    try:
        if not isinstance(endpoint["address"], str):
            raise ValueError("address must be text")
        ipaddress.ip_address(endpoint["address"])
    except (ValueError, TypeError, KeyError) as exc:
        raise NetworkProbeError("address must be an exact IPv4 or IPv6 literal") from exc
    if type(endpoint.get("port")) is not int or not 1 <= endpoint["port"] <= 65535:
        raise NetworkProbeError("port must be an integer between 1 and 65535")
    if endpoint.get("expected") not in {"reachable", "blocked"}:
        raise NetworkProbeError("expected must be reachable or blocked")
    if endpoint.get("protocol") not in {"tcp", "tls"}:
        raise NetworkProbeError("protocol must be tcp or tls")
    if endpoint["protocol"] == "tls":
        hostname = endpoint.get("server_name")
        if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", hostname):
            raise NetworkProbeError("TLS requires a bounded certificate server_name")


def run_plan(plan: Any) -> dict[str, Any]:
    config = validate_plan(plan)
    results: list[dict[str, Any]] = []
    context = ssl.create_default_context()
    for endpoint in config["endpoints"]:
        # An IP literal avoids confusing DNS failure with a blocked listener.
        # Any completed TCP handshake proves reachability, even if TLS fails.
        connected = False
        tls_verified = False
        observation = "transport_error"
        try:
            with socket.create_connection(
                (endpoint["address"], endpoint["port"]), timeout=config.get("timeout_seconds", 3)
            ) as connection:
                connected = True
                observation = "reachable"
                if endpoint["protocol"] == "tls":
                    with context.wrap_socket(connection, server_hostname=endpoint["server_name"]):
                        tls_verified = True
        except ssl.SSLError:
            observation = "tls_error"
        except ConnectionRefusedError:
            observation = "refused"
        except TimeoutError:
            observation = "timeout"
        except OSError:
            observation = "transport_error"
        blocked_observed = not connected and observation in {"refused", "timeout"}
        matched = (
            blocked_observed
            if endpoint["expected"] == "blocked"
            else connected and (endpoint["protocol"] == "tcp" or tls_verified)
        )
        results.append(
            {
                **{key: endpoint[key] for key in ("id", "address", "port", "protocol", "expected")},
                "observation": observation,
                "tcp_connected": connected,
                "tls_verified": tls_verified,
                "expectation_met": matched,
            }
        )
    return {
        "schema": "request-engine/network-evidence/v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "candidate": config["candidate"],
        "configuration_reference": config["configuration_reference"],
        "source_reference": config["source_reference"],
        "vantage": config["vantage"],
        "results": results,
        "outcome": "expectations_met" if all(r["expectation_met"] for r in results) else "failed",
        "production_certified": False,
        "requires_private_positive_baseline_and_firewall_review": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        with args.plan.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise NetworkProbeError("network plan exceeds the 64 KiB input cap")
        result = run_plan(json.loads(raw))
    except (NetworkProbeError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"Network probe rejected: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(result["outcome"])
    return 0 if result["outcome"] == "expectations_met" else 1


if __name__ == "__main__":
    raise SystemExit(main())
