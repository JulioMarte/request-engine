"""Explicitly remove one bounded batch of old, unusable WebAuthn challenges."""

from __future__ import annotations

import argparse
import json
import os
import sys

from request_engine.platform.db.webauthn_challenge_retention import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RETENTION_SECONDS,
    parse_integer_setting,
    run_retention_pass,
    validate_retention_configuration,
)

_DSN_ENV = "REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL"


def _config_from_environment() -> tuple[int, int]:
    retention = parse_integer_setting(
        os.environ.get(
            "REQUEST_ENGINE_WEBAUTHN_CHALLENGE_RETENTION_SECONDS",
            str(DEFAULT_RETENTION_SECONDS),
        ),
        name="retention seconds",
    )
    batch = parse_integer_setting(
        os.environ.get(
            "REQUEST_ENGINE_WEBAUTHN_CHALLENGE_RETENTION_BATCH_SIZE",
            str(DEFAULT_BATCH_SIZE),
        ),
        name="batch size",
    )
    return validate_retention_configuration(retention, batch)


def _run(dsn: str, *, retention_seconds: int, batch_size: int) -> int:
    return run_retention_pass(dsn, retention_seconds=retention_seconds, batch_size=batch_size)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform the bounded deletion")
    parser.add_argument("--retention-seconds", type=int)
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; this maintenance pass never runs implicitly")
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        parser.error(f"{_DSN_ENV} must contain a dedicated maintenance-login DSN")
    try:
        env_retention, env_batch = _config_from_environment()
        retention = env_retention if args.retention_seconds is None else args.retention_seconds
        batch = env_batch if args.batch_size is None else args.batch_size
        validate_retention_configuration(retention, batch)
        deleted = _run(dsn, retention_seconds=retention, batch_size=batch)
    except Exception:
        print("native_webauthn_challenge_retention_failed", file=sys.stderr)
        return 1
    print(json.dumps({"schema": "native-webauthn-challenge-retention/v1", "deleted": deleted}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
