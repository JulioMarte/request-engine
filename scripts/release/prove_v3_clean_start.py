#!/usr/bin/env python3
"""Prove the G19 candidate database is clean before applying V3 migrations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

APPLICATION_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")


def _scalar(query: str) -> int:
    env = os.environ.copy()
    result = subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atqc", query],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return int(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    schema_count = _scalar(
        "SELECT count(*) FROM pg_namespace WHERE nspname IN "
        "('request_engine','request_read','request_cmd','request_admin')"
    )
    public_table_count = _scalar(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    status = "PASS" if schema_count == 0 and public_table_count == 0 else "FAIL"
    payload = {
        "proof": "v3-production-like-clean-start",
        "status": status,
        "database": os.environ.get("PGDATABASE", "unknown"),
        "application_schemas_expected_absent": list(APPLICATION_SCHEMAS),
        "application_schema_count": schema_count,
        "public_base_table_count": public_table_count,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
