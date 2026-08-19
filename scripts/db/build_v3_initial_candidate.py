from __future__ import annotations

import argparse
import hashlib
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
PG_DUMP_CONTAINER_ENV = "REQUEST_ENGINE_PG_DUMP_CONTAINER"
DUMP_VERSION_PREFIXES = (
    "-- Dumped from database version ",
    "-- Dumped by pg_dump version ",
)

ROLE_PREAMBLE = """-- Request Engine V3 final-initial SQL payload.
-- Generated from the frozen post-G19 PostgreSQL catalog, not migration-history concatenation.
-- Production authority is the checked-in Alembic revision plus exact-head G17 evidence.

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


def _pg_dump_command(database: str) -> list[str]:
    container = os.environ.get(PG_DUMP_CONTAINER_ENV)
    if container:
        command = [
            "docker",
            "exec",
            container,
            "pg_dump",
            f"--username={os.environ.get('PGUSER', 'postgres')}",
        ]
    else:
        command = ["pg_dump"]

    command.extend(
        (
            "--schema-only",
            "--format=plain",
            "--no-comments",
            "--no-security-labels",
            f"--restrict-key={RESTRICT_KEY}",
            "--strict-names",
        )
    )
    for schema in APPLICATION_SCHEMAS:
        command.append(f"--schema={schema}")
    command.append(database)
    return command


def _pg_dump_schema(database: str) -> str:
    command = _pg_dump_command(database)
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


def _normalize_dump(dump: str) -> str:
    restrict_line = f"\\restrict {RESTRICT_KEY}"
    unrestrict_line = f"\\unrestrict {RESTRICT_KEY}"
    saw_restrict = False
    saw_unrestrict = False
    output: list[str] = []

    for line in dump.splitlines():
        if line == restrict_line:
            if saw_restrict:
                raise SystemExit("pg_dump emitted duplicate \\restrict markers")
            saw_restrict = True
            continue
        if line == unrestrict_line:
            if saw_unrestrict:
                raise SystemExit("pg_dump emitted duplicate \\unrestrict markers")
            saw_unrestrict = True
            continue
        if line.startswith(DUMP_VERSION_PREFIXES):
            continue
        if line.startswith("\\"):
            raise SystemExit(f"pg_dump emitted unsupported psql meta-command: {line}")
        output.append(line)

    if not saw_restrict or not saw_unrestrict:
        raise SystemExit("pg_dump output is missing the deterministic restrict markers")
    return "\n".join(output).rstrip() + "\n"


def render_initial(database: str) -> str:
    dump = _pg_dump_schema(database)
    if not dump.strip():
        raise SystemExit("pg_dump produced an empty final-initial candidate")
    return ROLE_PREAMBLE + _normalize_dump(dump)


def _require_reviewed_baseline(rendered: str) -> None:
    from migrations.v3_initial_payload import load_v3_initial_sql

    reviewed = load_v3_initial_sql()
    if rendered == reviewed:
        return
    generated_sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    reviewed_sha = hashlib.sha256(reviewed.encode("utf-8")).hexdigest()
    raise SystemExit(
        "generated final-initial SQL differs from the reviewed Alembic baseline "
        f"(generated={generated_sha}, reviewed={reviewed_sha})"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", default=os.environ.get("PGDATABASE"))
    parser.add_argument("--freeze-output", type=Path, default=DEFAULT_FREEZE_OUTPUT)
    parser.add_argument("--require-reviewed-baseline", action="store_true")
    args = parser.parse_args()

    if not args.database:
        raise SystemExit("--database or PGDATABASE is required")

    prove_candidate_freeze(args.freeze_output)
    rendered = render_initial(args.database)
    if args.require_reviewed_baseline:
        _require_reviewed_baseline(rendered)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
