#!/usr/bin/env python3
"""Fail a required aggregate job unless every GitHub Actions dependency passed."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any


def validate_required_needs(payload: object) -> list[str]:
    """Return actionable errors for malformed, missing, or unsuccessful needs."""

    if not isinstance(payload, Mapping) or not payload:
        return ["required dependency results are missing or empty"]

    errors: list[str] = []
    for name, details in sorted(payload.items(), key=lambda item: str(item[0])):
        if not isinstance(details, Mapping):
            errors.append(f"{name}: dependency result is malformed")
            continue
        result = details.get("result")
        if result != "success":
            errors.append(f"{name}: expected success, received {result!r}")
    return errors


def main() -> int:
    raw = os.environ.get("REQUIRED_NEEDS_JSON")
    if raw is None:
        print("Required CI prerequisite gate failed: REQUIRED_NEEDS_JSON is unset.")
        return 1

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Required CI prerequisite gate failed: invalid JSON: {exc}")
        return 1

    errors = validate_required_needs(payload)
    if errors:
        print("Required CI prerequisite gate failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Required CI prerequisite gate passed: {len(payload)} job(s) succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
