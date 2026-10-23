"""Materialize the 0047 rebaseline candidate from a clean PostgreSQL 18 source cluster.

Transitional scaffolding for the 2026-10-23 pre-production history collapse
(0001_initial + 0002..0047 -> new 0001_initial). It follows the PR #135
precedent (build_rebaseline_0094_candidate.sh): the effective product truth is a
full plain pg_dump of a database that contains only migration-owned state.

Differences from the 0094 builder, each deliberate:

* comments are kept (``--no-comments`` removed) because the head schema carries a
  migration-owned column comment; only ``COMMENT ON EXTENSION`` is dropped since
  ``CREATE EXTENSION`` recreates the extension's own comment identically and the
  statement would otherwise require extension ownership;
* installation-local identity is canonicalized by the script (the 0094 promotion
  did the identical rewrite by hand), so the produced payload is directly the
  canonical payload;
* four CHECK constraints whose source used `length(x) BETWEEN a AND b AND ...`
  are restored to that source form, because replaying pg_dump's deparsed text
  flattens the nested AND and the restored expression tree would deparse
  differently (logically identical, but not byte-exact DDL);
* the payload is split into <=120000-byte parts at line boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PART_LIMIT = 120_000

_NATIVE_INSERT = """INSERT INTO request_engine.identity_authorities (
    kind, issuer_or_environment
) VALUES (
    'native', 'request-engine-native'
);
"""
_WORKLOAD_INSERT = """INSERT INTO request_engine.identity_authorities (
    kind, issuer_or_environment
) VALUES (
    'workload', 'request-engine-workload'
);
"""
_PLATFORM_INSERT = """INSERT INTO request_engine.platform_instance (
    singleton_key,
    built_in_native_authority_id,
    built_in_workload_authority_id
)
SELECT 1, native.id, workload.id
FROM request_engine.identity_authorities AS native
CROSS JOIN request_engine.identity_authorities AS workload
WHERE native.kind = 'native'
  AND native.issuer_or_environment = 'request-engine-native'
  AND workload.kind = 'workload'
  AND workload.issuer_or_environment = 'request-engine-workload';
"""
_UUID = r"'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'"
_TS = r"'[0-9: .+-]+'"
_AUTHORITY = re.compile(
    rf"^INSERT INTO request_engine\.identity_authorities VALUES \({_UUID}, "
    rf"'(native|workload)', 'request-engine-(native|workload)', 'active', NULL, 1, "
    rf"{_TS}\);$"
)
_PLATFORM = re.compile(
    rf"^INSERT INTO request_engine\.platform_instance VALUES \(1, {_UUID}, 'unclaimed', 1, "
    rf"{_UUID}, {_UUID}, {_TS}, NULL, NULL, NULL\);$"
)


def _pg_dump(container: str, database: str, *flags: str) -> str:
    raw = subprocess.run(
        ["docker", "exec", "-e", "PGUSER=postgres", container, "pg_dump", *flags, database],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    kept: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("\\restrict ") or line.startswith("\\unrestrict "):
            continue
        if line.startswith("\\"):
            raise SystemExit(f"unexpected psql meta-command: {line.rstrip()!r}")
        if line.startswith("COMMENT ON EXTENSION "):
            continue
        kept.append(line)
    return "".join(kept)


def _canonicalize_identity(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    seen: dict[str, int] = {"native": 0, "workload": 0, "platform": 0}
    for line in lines:
        stripped = line.rstrip("\n")
        authority = _AUTHORITY.match(stripped)
        if authority is not None:
            kind = authority.group(1)
            if authority.group(2) != kind:
                raise SystemExit(f"unexpected built-in authority row: {stripped!r}")
            seen[kind] += 1
            out.append(_NATIVE_INSERT if kind == "native" else _WORKLOAD_INSERT)
            continue
        if stripped.startswith("INSERT INTO request_engine.identity_authorities"):
            raise SystemExit(f"unrecognized identity authority seed row: {stripped!r}")
        if _PLATFORM.match(stripped) is not None:
            seen["platform"] += 1
            out.append(_PLATFORM_INSERT)
            continue
        if stripped.startswith("INSERT INTO request_engine.platform_instance"):
            raise SystemExit(f"unrecognized platform instance seed row: {stripped!r}")
        out.append(line)
    if seen != {"native": 1, "workload": 1, "platform": 1}:
        raise SystemExit(f"installation identity canonicalization incomplete: {seen!r}")
    return "".join(out)


# pg_dump deparses ``length(x) BETWEEN a AND b AND <more>`` as a nested AND inside
# the outer AND list. Replaying that text flattens the tree, so the restored
# constraint is logically identical but deparses differently. Restoring the
# original BETWEEN source form reproduces the exact stored expression tree.
# Only the leftmost conjunct is affected: makeAndExpr flattens a left AND operand.
_NESTED_BETWEEN = re.compile(
    r"(?<=CHECK \(\()\(\(length\((\w+)\) >= (\d+)\) AND \(length\(\1\) <= (\d+)\)\) AND "
)
EXPECTED_BETWEEN_RESTORATIONS = 4


def _restore_between(text: str) -> str:
    restored = 0
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("    CONSTRAINT ") and " CHECK " in line:
            line, count = _NESTED_BETWEEN.subn(r"(length(\1) BETWEEN \2 AND \3) AND ", line)
            restored += count
        out.append(line)
    if restored != EXPECTED_BETWEEN_RESTORATIONS:
        raise SystemExit(f"unexpected nested BETWEEN constraint count: {restored}")
    return "".join(out)


def _split(payload: bytes) -> list[bytes]:
    parts: list[bytes] = []
    current = bytearray()
    for line in payload.splitlines(keepends=True):
        if len(line) > PART_LIMIT:
            raise SystemExit("a single dump line exceeds the part limit")
        if len(current) + len(line) > PART_LIMIT:
            parts.append(bytes(current))
            current = bytearray()
        current.extend(line)
    if current:
        parts.append(bytes(current))
    return parts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", default="request_engine_current")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)

    version = subprocess.run(
        ["docker", "exec", args.container, "pg_dump", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if " 18." not in version:
        raise SystemExit(f"rebaseline requires PostgreSQL 18 pg_dump, got {version!r}")

    full = _pg_dump(
        args.container,
        args.database,
        "--exclude-table=alembic_version",
        "--inserts",
        "--rows-per-insert=1",
    )
    (args.evidence / "source-full-dump.sql").write_bytes(full.encode("utf-8"))
    ddl = _pg_dump(
        args.container, args.database, "--schema-only", "--exclude-table=alembic_version"
    )
    (args.evidence / "source-schema-ddl.sql").write_bytes(ddl.encode("utf-8"))

    canonical = _restore_between(_canonicalize_identity(full)).encode("utf-8")
    for stale in args.baseline.glob("0001_schema.*.sql"):
        stale.unlink()
    parts = []
    for index, part in enumerate(_split(canonical), start=1):
        name = f"0001_schema.{index:02d}.sql"
        (args.baseline / name).write_bytes(part)
        parts.append(
            {"path": name, "bytes": len(part), "sha256": hashlib.sha256(part).hexdigest()}
        )
    summary = {
        "pg_dump_version": version,
        "source_artifact": {
            "bytes": len(full.encode("utf-8")),
            "sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
        },
        "bytes": len(canonical),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "materialized_parts": parts,
    }
    (args.evidence / "payload-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "materialized_parts"}))


if __name__ == "__main__":
    main()
