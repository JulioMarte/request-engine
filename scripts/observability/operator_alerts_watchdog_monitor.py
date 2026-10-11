"""Independent local monitor for the Prometheus Watchdog signal."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError
from urllib.request import urlopen


def read_latest_state(path: Path) -> str | None:
    try:
        states = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return states[-1] if states else None


def _watchdog_state(prometheus_url: str) -> str:
    try:
        with urlopen(f"{prometheus_url.rstrip('/')}/api/v1/alerts", timeout=2) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, URLError, ValueError):
        return "unreachable"
    if not isinstance(payload, dict):
        return "unreachable"
    body = cast(dict[str, Any], payload)
    if body.get("status") != "success":
        return "unreachable"
    data = body.get("data")
    if not isinstance(data, dict):
        return "unreachable"
    alerts = cast(dict[str, Any], data).get("alerts", [])
    if not isinstance(alerts, list):
        return "unreachable"
    for value in cast(list[Any], alerts):
        if not isinstance(value, dict):
            continue
        alert = cast(dict[str, Any], value)
        labels = alert.get("labels")
        if (
            isinstance(labels, dict)
            and cast(dict[str, Any], labels).get("alertname") == "Watchdog"
            and alert.get("state") == "firing"
        ):
            return "present"
    return "missing"


def _receiver_heartbeat_state(receiver_url: str, maximum_age: float) -> str:
    try:
        with urlopen(f"{receiver_url.rstrip('/')}/watchdog", timeout=2) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, URLError, ValueError):
        return "receiver_unreachable"
    if not isinstance(payload, dict):
        return "receiver_unreachable"
    timestamp = cast(dict[str, Any], payload).get("last_accepted_timestamp")
    if timestamp is None:
        return "heartbeat_missing"
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not math.isfinite(timestamp)
    ):
        return "receiver_unreachable"
    age = time.time() - timestamp
    if age < -2 or age > maximum_age:
        return "heartbeat_stale"
    return "present"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--receiver-url")
    parser.add_argument("--heartbeat-max-age-seconds", type=float, default=15.0)
    parser.add_argument("--read-latest", action="store_true")
    args = parser.parse_args()
    if args.read_latest:
        latest = read_latest_state(args.output)
        if latest is not None:
            print(latest)
        return
    if args.prometheus_url is None:
        parser.error("--prometheus-url is required unless --read-latest is used")
    if (
        not math.isfinite(args.poll_seconds)
        or args.poll_seconds <= 0
        or not math.isfinite(args.heartbeat_max_age_seconds)
        or args.heartbeat_max_age_seconds <= 0
    ):
        parser.error("poll interval and heartbeat maximum age must be finite and positive")
    previous: str | None = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    while True:
        current = _watchdog_state(args.prometheus_url)
        if current == "present" and args.receiver_url is not None:
            current = _receiver_heartbeat_state(args.receiver_url, args.heartbeat_max_age_seconds)
        if current != previous:
            with args.output.open("a", encoding="utf-8") as stream:
                stream.write(f"{current}\n")
            previous = current
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
