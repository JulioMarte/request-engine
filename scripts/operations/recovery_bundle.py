#!/usr/bin/env python3
"""Create, verify and restore encrypted Request Engine recovery bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, unquote, urlparse

_MANIFEST = "manifest.json"
_POSTGRES_DUMP = "postgres.dump"
_OPENBAO_SNAPSHOT = "openbao.snap"
_TRUE: Final = frozenset({"1", "true", "yes", "on"})
_PG_QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "application_name": "PGAPPNAME",
    "options": "PGOPTIONS",
}


class RecoveryBundleError(RuntimeError):
    pass


def _require_program(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RecoveryBundleError(f"required program is not installed: {name}")
    return resolved


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RecoveryBundleError(f"required environment variable is missing: {name}")
    return value


def _postgres_environment(dsn: str) -> tuple[dict[str, str], str]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RecoveryBundleError("PostgreSQL DSN must use postgres:// or postgresql://")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise RecoveryBundleError("PostgreSQL DSN must include host and database")
    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname
    env["PGPORT"] = str(parsed.port or 5432)
    env["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    if parsed.username is not None:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    query = parse_qs(parsed.query, keep_blank_values=False)
    unsupported = set(query) - set(_PG_QUERY_ENV)
    if unsupported:
        raise RecoveryBundleError(
            "unsupported PostgreSQL DSN query parameters: "
            + ", ".join(sorted(unsupported))
        )
    for key, values in query.items():
        if len(values) != 1:
            raise RecoveryBundleError(f"PostgreSQL DSN parameter must be singular: {key}")
        env[_PG_QUERY_ENV[key]] = values[0]
    return env, env["PGDATABASE"]


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fact(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_manifest(root: Path) -> Path:
    files = [root / _POSTGRES_DUMP, root / _OPENBAO_SNAPSHOT]
    manifest = {
        "schema": "request-engine/recovery-bundle/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "files": [_file_fact(path) for path in files],
    }
    target = root / _MANIFEST
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _pack(root: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as bundle:
        for name in (_MANIFEST, _POSTGRES_DUMP, _OPENBAO_SNAPSHOT):
            bundle.add(root / name, arcname=name, recursive=False)


def _encrypt(archive: Path, output: Path, recipient: str) -> None:
    age = _require_program("age")
    _run([age, "-r", recipient, "-o", str(output), str(archive)])


def _copy_offsite(artifact: Path, template: str) -> None:
    parts = shlex.split(template)
    if not parts or not any("{artifact}" in part for part in parts):
        raise RecoveryBundleError("offsite command must contain the {artifact} placeholder")
    command = [
        part.replace("{artifact}", str(artifact)).replace("{name}", artifact.name)
        for part in parts
    ]
    _run(command)


def create_backup(args: argparse.Namespace) -> Path:
    pg_dump = _require_program("pg_dump")
    bao = _require_program(args.bao_command)
    dsn = _require_env(args.postgres_dsn_env)
    pg_env, _database = _postgres_environment(dsn)
    recipient = args.age_recipient or _require_env(args.age_recipient_env)
    offsite = args.offsite_command or os.environ.get(args.offsite_command_env)
    if not args.local_only and not offsite:
        raise RecoveryBundleError(
            f"off-host copy is required; set {args.offsite_command_env} or use --local-only"
        )

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = output_dir / f"request-engine-recovery-{timestamp}.tar.gz.age"
    if final.exists():
        raise RecoveryBundleError(f"refusing to overwrite existing backup: {final}")

    with tempfile.TemporaryDirectory(prefix="request-engine-recovery-") as raw:
        root = Path(raw)
        postgres_dump = root / _POSTGRES_DUMP
        openbao_snapshot = root / _OPENBAO_SNAPSHOT
        archive = root / "recovery.tar.gz"

        _run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(postgres_dump),
            ],
            env=pg_env,
        )
        _run([bao, "operator", "raft", "snapshot", "save", str(openbao_snapshot)])
        _write_manifest(root)
        _pack(root, archive)
        _encrypt(archive, final, recipient)

    if offsite:
        _copy_offsite(final, offsite)
    return final


def _decrypt(bundle: Path, output: Path, identity: Path) -> None:
    age = _require_program("age")
    _run([age, "-d", "-i", str(identity), "-o", str(output), str(bundle)])


def _extract_verified(bundle: Path, identity: Path, root: Path) -> dict[str, object]:
    archive = root / "recovery.tar.gz"
    _decrypt(bundle, archive, identity)
    extracted = root / "extracted"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as source:
        names = set(source.getnames())
        expected = {_MANIFEST, _POSTGRES_DUMP, _OPENBAO_SNAPSHOT}
        if names != expected:
            raise RecoveryBundleError(f"unexpected recovery bundle members: {sorted(names)}")
        source.extractall(extracted, filter="data")

    manifest_value: object = json.loads((extracted / _MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest_value, dict):
        raise RecoveryBundleError("recovery manifest is not an object")
    manifest = manifest_value
    if manifest.get("schema") != "request-engine/recovery-bundle/v1":
        raise RecoveryBundleError("unsupported recovery bundle schema")
    facts = manifest.get("files")
    if not isinstance(facts, list):
        raise RecoveryBundleError("recovery manifest files are invalid")
    expected_names = {_POSTGRES_DUMP, _OPENBAO_SNAPSHOT}
    seen: set[str] = set()
    for value in facts:
        if not isinstance(value, dict):
            raise RecoveryBundleError("recovery manifest file fact is invalid")
        name = value.get("name")
        sha = value.get("sha256")
        size = value.get("size")
        if not isinstance(name, str) or name not in expected_names or name in seen:
            raise RecoveryBundleError("recovery manifest contains an unexpected file")
        path = extracted / name
        if (
            not isinstance(sha, str)
            or not isinstance(size, int)
            or path.stat().st_size != size
            or _sha256(path) != sha
        ):
            raise RecoveryBundleError(f"recovery bundle checksum mismatch: {name}")
        seen.add(name)
    if seen != expected_names:
        raise RecoveryBundleError("recovery manifest is incomplete")
    return manifest


def verify_backup(args: argparse.Namespace) -> None:
    bundle = Path(args.bundle).resolve()
    identity = Path(_require_env(args.age_identity_file_env)).resolve()
    with tempfile.TemporaryDirectory(prefix="request-engine-verify-") as raw:
        _extract_verified(bundle, identity, Path(raw))


def _require_restore_fence() -> None:
    value = os.environ.get("REQUEST_ENGINE_OUTBOUND_FENCED", "").strip().lower()
    if value not in _TRUE:
        raise RecoveryBundleError(
            "restore requires REQUEST_ENGINE_OUTBOUND_FENCED=true before any destructive action"
        )


def restore_backup(args: argparse.Namespace) -> None:
    if not args.confirm_destructive:
        raise RecoveryBundleError("restore requires --confirm-destructive")
    _require_restore_fence()
    pg_restore = _require_program("pg_restore")
    bao = _require_program(args.bao_command)
    dsn = _require_env(args.postgres_dsn_env)
    pg_env, database = _postgres_environment(dsn)
    bundle = Path(args.bundle).resolve()
    identity = Path(_require_env(args.age_identity_file_env)).resolve()

    with tempfile.TemporaryDirectory(prefix="request-engine-restore-") as raw:
        root = Path(raw)
        _extract_verified(bundle, identity, root)
        extracted = root / "extracted"
        _run(
            [
                pg_restore,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--dbname",
                database,
                str(extracted / _POSTGRES_DUMP),
            ],
            env=pg_env,
        )
        _run(
            [
                bao,
                "operator",
                "raft",
                "snapshot",
                "restore",
                str(extracted / _OPENBAO_SNAPSHOT),
            ]
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup")
    backup.add_argument("--postgres-dsn-env", default="REQUEST_ENGINE_BACKUP_DATABASE_URL")
    backup.add_argument("--output-dir", default="./backups")
    backup.add_argument("--bao-command", default="bao")
    backup.add_argument("--age-recipient")
    backup.add_argument("--age-recipient-env", default="REQUEST_ENGINE_BACKUP_AGE_RECIPIENT")
    backup.add_argument("--offsite-command")
    backup.add_argument(
        "--offsite-command-env",
        default="REQUEST_ENGINE_BACKUP_OFFSITE_COMMAND",
    )
    backup.add_argument("--local-only", action="store_true")
    backup.set_defaults(handler=create_backup)

    verify = sub.add_parser("verify")
    verify.add_argument("bundle")
    verify.add_argument(
        "--age-identity-file-env",
        default="REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE",
    )
    verify.set_defaults(handler=verify_backup)

    restore = sub.add_parser("restore")
    restore.add_argument("bundle")
    restore.add_argument("--postgres-dsn-env", default="REQUEST_ENGINE_RESTORE_DATABASE_URL")
    restore.add_argument("--bao-command", default="bao")
    restore.add_argument(
        "--age-identity-file-env",
        default="REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE",
    )
    restore.add_argument("--confirm-destructive", action="store_true")
    restore.set_defaults(handler=restore_backup)
    return parser



def main() -> int:
    args = _parser().parse_args()
    try:
        result = args.handler(args)
    except (
        RecoveryBundleError,
        subprocess.CalledProcessError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise SystemExit(f"recovery bundle operation failed: {exc}") from exc
    if isinstance(result, Path):
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
