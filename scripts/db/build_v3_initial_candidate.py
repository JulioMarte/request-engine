from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FREEZE_PROOF = ROOT / "scripts/release/prove_v3_candidate_freeze.py"
DEFAULT_FREEZE_OUTPUT = ROOT / ".phase6/v3-candidate-freeze.json"
APPLICATION_SCHEMAS = (
    "request_engine",
    "request_read",
    "request_cmd",
    "request_admin",
)
RESTRICT_KEY = "RequestEngineV3Baseline"

ROLE_PREAMBLE = """-- Request Engine V3 final-initial release candidate.
-- Generated from the frozen post-G19 PostgreSQL catalog, not migration-history concatenation.
-- This file is not blessed as production 0001_initial until G17 passes exact-head evidence.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_schema_owner') THEN
        CREATE ROLE request_engine_schema_owner NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_app') THEN
        CREATE ROLE request_engine_app NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_worker') THEN
        CREATE ROLE request_engine_worker NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_admin') THEN
        CREATE ROLE request_engine_admin NOLOGIN BYPASSRLS;
    END IF;
END
$roles$;

ALTER ROLE request_engine_schema_owner NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_app NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_worker NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_admin NOLOGIN BYPASSRLS;

CREATE EXTENSION IF NOT EXISTS btree_gist;

"""


def prove_candidate_freeze(output: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(FREEZE_PROOF), "--output", str(output)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("refusing to build 0001 candidate because the V3 candidate freeze failed")


def _pg_dump_schema(database: str) -> str:
    command = [
        "pg_dump",
        "--schema-only",
        "--format=plain",
        "--no-comments",
        "--no-security-labels",
        f"--restrict-key={RESTRICT_KEY}",
        "--strict-names",
    ]
    for schema in APPLICATION_SCHEMAS:
        command.append(f"--schema={schema}")
    command.append(database)

    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"pg_dump failed while building final-initial candidate: {detail}")
    if result.stderr.strip():
        raise SystemExit(
            "pg_dump emitted warnings while building final-initial candidate: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def render_initial(database: str) -> str:
    dump = _pg_dump_schema(database)
    if not dump.strip():
        raise SystemExit("pg_dump produced an empty final-initial candidate")
    return ROLE_PREAMBLE + dump.rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", default=os.environ.get("PGDATABASE"))
    parser.add_argument("--freeze-output", type=Path, default=DEFAULT_FREEZE_OUTPUT)
    args = parser.parse_args()

    if not args.database:
        raise SystemExit("--database or PGDATABASE is required")

    prove_candidate_freeze(args.freeze_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_initial(args.database), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
