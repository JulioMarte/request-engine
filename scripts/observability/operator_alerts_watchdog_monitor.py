"""Independent local monitor for the Prometheus Watchdog signal."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
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
    except (OSError, TimeoutError, URLError):
        return "unreachable"
    if payload.get("status") != "success":
        return "unreachable"
    alerts = payload.get("data", {}).get("alerts", [])
    if any(
        alert.get("labels", {}).get("alertname") == "Watchdog" and alert.get("state") == "firing"
        for alert in alerts
    ):
        return "present"
    return "missing"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--read-latest", action="store_true")
    args = parser.parse_args()
    if args.read_latest:
        latest = read_latest_state(args.output)
        if latest is not None:
            print(latest)
        return
    if args.prometheus_url is None:
        parser.error("--prometheus-url is required unless --read-latest is used")
    previous: str | None = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    while True:
        current = _watchdog_state(args.prometheus_url)
        if current != previous:
            with args.output.open("a", encoding="utf-8") as stream:
                stream.write(f"{current}\n")
            previous = current
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
