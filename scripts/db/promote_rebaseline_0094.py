from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROOF_HEAD = "a37ee1b7a5e698890a0f558461c271114e6bd3ec"
PROOF_RUN_ID = 36352879969
PROOF_RUN_NUMBER = 3
EXPECTED_SOURCE_HEAD = "0094_managed_oidc_readiness"
CHUNK_LIMIT = 120_000
ALLOWED_SINCE_PROOF = {
    ".github/workflows/rebaseline-0094.yml",
    "scripts/db/promote_rebaseline_0094.py",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _require_proof_ancestry() -> None:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", PROOF_HEAD, "HEAD"],
        cwd=ROOT,
        check=True,
    )
    changed = {
        line
        for line in _run("git", "diff", "--name-only", f"{PROOF_HEAD}..HEAD").splitlines()
        if line
    }
    unexpected = sorted(changed - ALLOWED_SINCE_PROOF)
    if unexpected:
        raise RuntimeError(
            "repository changed after the certified proof head outside promotion infrastructure: "
            + ", ".join(unexpected)
        )


def _validate_artifact(artifact: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    required = (
        "0001_roles.sql",
        "0001_schema.sql",
        "SHA256SUMS",
        "provenance.json",
        "schema-comparison.json",
        "clean-schema-comparison.json",
        "clean-role-comparison.json",
        "source-schema-catalog.json",
        "source-role-catalog.json",
        "source-schema-cohesion.json",
    )
    missing = [name for name in required if not (artifact / name).is_file()]
    if missing:
        raise RuntimeError(f"proof artifact is incomplete: {missing}")

    provenance = _load(artifact / "provenance.json")
    if provenance.get("source_commit") != PROOF_HEAD:
        raise RuntimeError("proof artifact was not materialized from the certified source commit")
    if provenance.get("source_head") != EXPECTED_SOURCE_HEAD:
        raise RuntimeError("proof artifact has an unexpected Alembic source head")
    if "PostgreSQL) 18." not in str(provenance.get("pg_dump_version", "")):
        raise RuntimeError("proof artifact was not materialized with PostgreSQL 18 pg_dump")

    for name in (
        "schema-comparison.json",
        "clean-schema-comparison.json",
        "clean-role-comparison.json",
    ):
        comparison = _load(artifact / name)
        if comparison.get("equivalent") is not True or comparison.get("first_difference") is not None:
            raise RuntimeError(f"{name} does not certify exact equivalence")

    expected_hashes: dict[str, str] = {}
    for line in (artifact / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, path = line.split(maxsplit=1)
        expected_hashes[Path(path).name] = digest
    for name in ("0001_roles.sql", "0001_schema.sql"):
        digest = _sha256((artifact / name).read_bytes())
        if expected_hashes.get(name) != digest:
            raise RuntimeError(f"{name} does not match the certified artifact checksum")

    schema = (artifact / "0001_schema.sql").read_text(encoding="utf-8")
    meta = [line for line in schema.splitlines() if line.startswith("\\")]
    if meta:
        raise RuntimeError(f"candidate contains psql meta-command(s): {meta[:3]!r}")

    return _load(artifact / "source-schema-catalog.json"), _load(
        artifact / "source-role-catalog.json"
    )


def _split_schema(payload: bytes) -> list[bytes]:
    chunks: list[bytes] = []
    current = bytearray()
    for line in payload.splitlines(keepends=True):
        if len(line) > CHUNK_LIMIT:
            raise RuntimeError("schema contains a line larger than the accepted chunk limit")
        if current and len(current) + len(line) > CHUNK_LIMIT:
            chunks.append(bytes(current))
            current = bytearray()
        current.extend(line)
    if current:
        chunks.append(bytes(current))
    if b"".join(chunks) != payload:
        raise RuntimeError("schema split was not byte-preserving")
    return chunks


def _write_baseline(
    artifact: Path,
    schema_catalog: dict[str, Any],
    role_catalog: dict[str, Any],
) -> None:
    baseline = ROOT / "migrations" / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)

    schema_payload = (artifact / "0001_schema.sql").read_bytes()
    role_payload = (artifact / "0001_roles.sql").read_bytes()
    chunks = _split_schema(schema_payload)

    for old in baseline.glob("0001_schema.*.sql"):
        old.unlink()
    parts: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        name = f"0001_schema.{index:02d}.sql"
        (baseline / name).write_bytes(chunk)
        parts.append(
            {
                "path": name,
                "bytes": len(chunk),
                "sha256": _sha256(chunk),
            }
        )
    (baseline / "0001_roles.sql").write_bytes(role_payload)

    expected_roles: dict[str, dict[str, Any]] = {}
    for item in role_catalog["roles"]:
        role = dict(item)
        name = str(role.pop("role_name"))
        expected_roles[name] = role

    counts = schema_catalog["counts"]
    relations = schema_catalog["relations"]
    tables = sum(1 for row in relations if row["relation_kind"] in {"r", "p"})
    views = sum(1 for row in relations if row["relation_kind"] in {"v", "m"})
    manifest = {
        "schema_version": 1,
        "source": {
            "branch": "feature/rebaseline-0094",
            "head_sha": PROOF_HEAD,
            "ci_run_number": PROOF_RUN_NUMBER,
            "ci_run_id": PROOF_RUN_ID,
            "postgresql_version": "18.6",
            "pg_dump_version": "pg_dump (PostgreSQL) 18.6 (Debian 18.6-1.pgdg13+2)",
            "source_alembic_head": EXPECTED_SOURCE_HEAD,
        },
        "schema_payload": {
            "source_artifact_name": "rebaseline-0094-candidate/0001_schema.sql",
            "bytes": len(schema_payload),
            "sha256": _sha256(schema_payload),
            "materialized_parts": parts,
        },
        "role_bootstrap": {
            "source_artifact_name": "rebaseline-0094-candidate/0001_roles.sql",
            "path": "0001_roles.sql",
            "bytes": len(role_payload),
            "sha256": _sha256(role_payload),
            "expected_roles": expected_roles,
            "role_memberships": role_catalog["role_memberships"],
            "role_settings": role_catalog["role_settings"],
        },
        "effective_model": {
            "relations": counts["relations"],
            "tables": tables,
            "views": views,
            "columns": counts["columns"],
            "constraints": counts["constraints"],
            "indexes": counts["indexes"],
            "routines": counts["routines"],
            "triggers": counts["triggers"],
            "policies": counts["policies"],
            "roles": role_catalog["counts"]["roles"],
            "role_memberships": role_catalog["counts"]["role_memberships"],
            "column_grants": counts["column_grants"],
        },
        "proof": {
            "historical_chain_to_0094": True,
            "candidate_schema_equivalent": True,
            "candidate_roles_equivalent": True,
            "clean_postgresql18_install_equivalent": True,
            "ci_run_id": PROOF_RUN_ID,
            "ci_run_number": PROOF_RUN_NUMBER,
            "proof_head_sha": PROOF_HEAD,
            "schema_comparison_first_difference": None,
        },
    }
    (baseline / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_loader() -> None:
    loader = r'''from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from psycopg import ClientCursor

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
APPLICATION_SCHEMAS = ("request_admin", "request_cmd", "request_engine", "request_read")
_MANAGED_ROLE_PATTERNS = ("request_engine_%", "request_platform_%", "request_bootstrap_%")
_ROLE_NAME = re.compile(r'^CREATE ROLE "([^"]+)" WITH .+;$')
_ROLE_QUERY = """
    SELECT rolname,
           rolsuper,
           rolinherit,
           rolcreaterole,
           rolcreatedb,
           rolcanlogin,
           rolreplication,
           rolbypassrls,
           rolconnlimit,
           rolvaliduntil::text,
           rolpassword IS NOT NULL
    FROM pg_authid
    WHERE rolname LIKE ANY(%s)
    ORDER BY rolname
"""
_MEMBERSHIP_QUERY = """
    SELECT parent.rolname, member.rolname
    FROM pg_auth_members membership
    JOIN pg_roles parent ON parent.oid = membership.roleid
    JOIN pg_roles member ON member.oid = membership.member
    WHERE parent.rolname LIKE ANY(%s)
       OR member.rolname LIKE ANY(%s)
    ORDER BY parent.rolname, member.rolname
"""
_SETTING_QUERY = """
    SELECT role.rolname, COALESCE(database.datname, ''), setting.setconfig
    FROM pg_db_role_setting setting
    JOIN pg_roles role ON role.oid = setting.setrole
    LEFT JOIN pg_database database ON database.oid = setting.setdatabase
    WHERE role.rolname LIKE ANY(%s)
    ORDER BY role.rolname, database.datname
"""
_ROLE_FIELDS = (
    "superuser",
    "inherit",
    "create_role",
    "create_db",
    "can_login",
    "replication",
    "bypass_rls",
    "connection_limit",
    "valid_until",
    "has_password",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported accepted baseline manifest")
    return payload


def _verified_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_bytes:
        raise RuntimeError(f"{path.name}: expected {expected_bytes} bytes, found {len(payload)}")
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise RuntimeError(f"{path.name}: expected sha256 {expected_sha256}, found {digest}")
    return payload


def load_schema_sql() -> str:
    manifest = _manifest()["schema_payload"]
    payloads: list[bytes] = []
    for part in manifest["materialized_parts"]:
        payloads.append(
            _verified_file(
                ROOT / part["path"],
                expected_bytes=part["bytes"],
                expected_sha256=part["sha256"],
            )
        )
    payload = b"".join(payloads)
    if len(payload) != manifest["bytes"]:
        raise RuntimeError("baseline schema byte length does not match manifest")
    if _sha256(payload) != manifest["sha256"]:
        raise RuntimeError("baseline schema checksum does not match manifest")
    text = payload.decode("utf-8")
    if any(line.startswith("\\") for line in text.splitlines()):
        raise RuntimeError("baseline schema contains a psql meta-command")
    return text


def load_role_statements() -> dict[str, str]:
    role_manifest = _manifest()["role_bootstrap"]
    payload = _verified_file(
        ROOT / role_manifest["path"],
        expected_bytes=role_manifest["bytes"],
        expected_sha256=role_manifest["sha256"],
    )
    statements: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        statement = line.strip()
        if not statement or statement.startswith("--"):
            continue
        match = _ROLE_NAME.fullmatch(statement)
        if match is None:
            raise RuntimeError("baseline role bootstrap contains an unexpected statement")
        role_name = match.group(1)
        if role_name in statements:
            raise RuntimeError(f"duplicate baseline role statement: {role_name}")
        statements[role_name] = statement

    expected_roles = role_manifest["expected_roles"]
    if set(statements) != set(expected_roles):
        raise RuntimeError("baseline role statements do not match manifest role names")
    if len(statements) != _manifest()["effective_model"]["roles"]:
        raise RuntimeError("baseline role bootstrap count does not match manifest")
    return statements


def _actual_roles(cursor: ClientCursor[Any]) -> dict[str, dict[str, Any]]:
    rows = cursor.execute(_ROLE_QUERY, (list(_MANAGED_ROLE_PATTERNS),)).fetchall()
    return {str(row[0]): dict(zip(_ROLE_FIELDS, row[1:], strict=True)) for row in rows}


def require_clean_database(driver_connection: Any) -> None:
    with ClientCursor(driver_connection) as cursor:
        rows = cursor.execute(
            """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname = ANY(%s)
            ORDER BY nspname
            """,
            (list(APPLICATION_SCHEMAS),),
        ).fetchall()
    if rows:
        names = ", ".join(str(row[0]) for row in rows)
        raise RuntimeError(
            "accepted 0001 requires a clean database; existing Request Engine schemas: " + names
        )


def ensure_exact_roles(driver_connection: Any) -> None:
    role_manifest = _manifest()["role_bootstrap"]
    expected_roles = role_manifest["expected_roles"]
    statements = load_role_statements()

    with ClientCursor(driver_connection) as cursor:
        actual = _actual_roles(cursor)
        unexpected = sorted(set(actual) - set(expected_roles))
        if unexpected:
            raise RuntimeError(
                "unexpected Request Engine managed roles already exist: " + ", ".join(unexpected)
            )

        for role_name in sorted(set(expected_roles) - set(actual)):
            cursor.execute(statements[role_name])

        actual = _actual_roles(cursor)
        if set(actual) != set(expected_roles):
            raise RuntimeError(
                "Request Engine role bootstrap did not produce the expected role set"
            )
        for role_name, expected in expected_roles.items():
            if actual[role_name] != expected:
                raise RuntimeError(
                    f"existing Request Engine role {role_name} does not match audited topology"
                )

        patterns = list(_MANAGED_ROLE_PATTERNS)
        memberships = cursor.execute(_MEMBERSHIP_QUERY, (patterns, patterns)).fetchall()
        if memberships != role_manifest["role_memberships"]:
            raise RuntimeError("Request Engine roles have unexpected role memberships")

        settings = cursor.execute(_SETTING_QUERY, (patterns,)).fetchall()
        if settings != role_manifest["role_settings"]:
            raise RuntimeError("Request Engine roles have unexpected role settings")
'''
    (ROOT / "migrations" / "baseline" / "loader.py").write_text(loader, encoding="utf-8")


def _write_docs() -> None:
    baseline_readme = f"""# PostgreSQL baseline

This directory is the canonical, immutable payload for Request Engine Alembic revision 0001_initial.

The current baseline was materialized from the audited PostgreSQL 18.6 effective model at historical Alembic head {EXPECTED_SOURCE_HEAD} and commit {PROOF_HEAD}. GitHub Actions run {PROOF_RUN_ID} proved all three promotion gates before the historical chain was removed:

1. 0001 through 0094 installed successfully on PostgreSQL 18;
2. the materialized candidate reproduced the effective schema and role catalogs exactly;
3. the candidate installed by itself on a completely clean PostgreSQL 18 cluster and reproduced those catalogs again.

manifest.json pins the complete schema checksum, every materialized part, the ten-role bootstrap topology, accepted effective-model counts and the proof provenance. loader.py verifies those checksums and exact managed-role contract before 0001_initial executes the SQL.

After this rebaseline, migrations/versions/0001_initial.py is the only historical revision. Future schema evolution appends new 0002+ revisions. Never regenerate this payload merely to make a later migration easier; another destructive rebaseline requires a new explicit audit and clean-cluster equivalence proof.
"""
    (ROOT / "migrations" / "baseline" / "README.md").write_text(
        baseline_readme,
        encoding="utf-8",
    )

    path = ROOT / "migrations" / "README.md"
    content = path.read_text(encoding="utf-8")
    content = content.replace(
        "It bootstraps the six audited Request Engine roles",
        "It bootstraps the ten audited Request Engine/platform bootstrap roles",
    )
    old_counts = """99 relations = 90 tables + 9 views
1,085 columns
1,575 validated constraints
276 indexes
145 routines
162 triggers
84 RLS policies
6 Request Engine roles
0 role memberships
12 column grants"""
    new_counts = """151 relations = 142 tables + 9 views
1,654 columns
2,441 validated constraints
404 indexes
210 routines
208 triggers
96 RLS policies
10 Request Engine/platform bootstrap roles
0 role memberships
677 column grants"""
    if old_counts not in content:
        raise RuntimeError("migration README accepted-model block changed unexpectedly")
    content = content.replace(old_counts, new_counts)
    old_history = (
        "The old V3 Base85 payload, V3 candidate SQL, feature-step helper modules and the "
        "pre-rebaseline " + chr(96) + "0002..0050" + chr(96) + " chain are intentionally "
        "absent from current HEAD. Their provenance remains in Git history and historical "
        "documentation; keeping dead executable migration machinery beside the accepted "
        "baseline would create a false second authority."
    )
    new_history = (
        "The old V3 payloads, candidate SQL, feature-step helper modules and the certified "
        "pre-rebaseline 0002..0094 chain are intentionally absent from current HEAD. Their "
        "provenance remains in Git history and in GitHub Actions run 36352879969; keeping "
        "dead executable migration machinery beside the accepted baseline would create a "
        "false second authority."
    )
    if old_history not in content:
        raise RuntimeError("migration README history paragraph changed unexpectedly")
    content = content.replace(old_history, new_history)
    path.write_text(content, encoding="utf-8")


def _collapse_migration_chain() -> None:
    versions = ROOT / "migrations" / "versions"
    for path in versions.glob("*.py"):
        if path.name in {"0001_initial.py", "__init__.py"}:
            continue
        path.unlink()


def _write_post_promotion_workflow() -> None:
    content = r'''name: PostgreSQL 18 promoted baseline proof

on:
  push:
    branches:
      - feature/rebaseline-0094
  workflow_dispatch:

permissions:
  contents: read

env:
  UV_VERSION: "0.12.5"

jobs:
  promoted-baseline:
    name: Prove promoted 0001 and current product
    runs-on: ubuntu-24.04
    timeout-minutes: 40
    services:
      postgres:
        image: postgres:18
        env:
          POSTGRES_DB: request_engine_current
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d request_engine_current"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 20
    env:
      PGHOST: 127.0.0.1
      PGPORT: "5432"
      PGDATABASE: request_engine_current
      PGUSER: postgres
      PGPASSWORD: postgres
      MIGRATION_DATABASE_URL: postgresql+psycopg://postgres:postgres@127.0.0.1:5432/request_engine_current
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b
        with:
          version: ${{ env.UV_VERSION }}
          enable-cache: true
          cache-dependency-glob: uv.lock
      - name: Install project
        run: uv sync --all-groups
      - name: Require collapsed Alembic history
        run: |
          mapfile -t revisions < <(find migrations/versions -maxdepth 1 -type f -name '*.py' ! -name '__init__.py' -printf '%f\\n' | sort)
          printf 'active revisions: %s\\n' "${revisions[*]}"
          [[ "${#revisions[@]}" -eq 1 ]]
          [[ "${revisions[0]}" == "0001_initial.py" ]]
          mapfile -t heads < <(uv run alembic heads | awk 'NF {print $1}')
          [[ "${#heads[@]}" -eq 1 ]]
          [[ "${heads[0]}" == "0001_initial" ]]
      - name: Run baseline contract tests
        run: >-
          uv run pytest
          tests/architecture/test_alembic_revision_contract.py
          tests/architecture/test_alembic_revision_identifiers.py
          tests/architecture/test_baseline_repository_contract.py
          tests/unit/test_baseline_loader.py
          tests/unit/test_verify_accepted_baseline.py
          -q --tb=short
      - name: Run canonical current-product proof
        run: bash scripts/ci/run_current_product.sh
      - name: Upload promoted-baseline evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: promoted-baseline-proof
          path: .ci/current-product/
          include-hidden-files: true
          if-no-files-found: warn
          retention-days: 30
'''
    content = content.replace("$", "$")
    (ROOT / ".github" / "workflows" / "rebaseline-0094.yml").write_text(
        content,
        encoding="utf-8",
    )


def main() -> None:
    artifact = Path(os.environ.get("REBASELINE_PROOF_DIR", ".ci/rebaseline-proof"))
    if not artifact.is_absolute():
        artifact = ROOT / artifact

    _require_proof_ancestry()
    schema_catalog, role_catalog = _validate_artifact(artifact)
    _write_baseline(artifact, schema_catalog, role_catalog)
    _write_loader()
    _write_docs()
    _collapse_migration_chain()
    _write_post_promotion_workflow()

    generator = ROOT / "scripts" / "db" / "build_rebaseline_0094_candidate.sh"
    generator.unlink(missing_ok=True)

    Path(__file__).unlink()

    subprocess.run(
        [
            "git",
            "diff",
            "--check",
            "--",
            ".",
            ":(exclude)migrations/baseline/0001_schema.*.sql",
        ],
        cwd=ROOT,
        check=True,
    )
    remaining = sorted(
        p.name
        for p in (ROOT / "migrations" / "versions").glob("*.py")
        if p.name != "__init__.py"
    )
    if remaining != ["0001_initial.py"]:
        raise RuntimeError(f"migration collapse incomplete: {remaining}")

    print(
        "promotion prepared: certified 0094 truth is now canonical 0001; "
        "historical 0002..0094 removed"
    )


if __name__ == "__main__":
    main()
