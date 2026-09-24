from __future__ import annotations

import importlib.util
import json
import os
import tarfile
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "operations" / "recovery_bundle.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recovery_bundle_test_target", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_dsn_moves_password_to_child_environment() -> None:
    module = _module()
    env, database = module._postgres_environment(  # type: ignore[attr-defined]
        "postgresql://backup-user:p%40ss@db.example.test:5544/request_engine"
        "?sslmode=require&connect_timeout=4"
    )
    assert database == "request_engine"
    assert env["PGUSER"] == "backup-user"
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGHOST"] == "db.example.test"
    assert env["PGPORT"] == "5544"
    assert env["PGSSLMODE"] == "require"
    assert env["PGCONNECT_TIMEOUT"] == "4"


def test_postgres_dsn_rejects_uncontrolled_query_parameters() -> None:
    module = _module()
    error = cast(type[RuntimeError], module.RecoveryBundleError)  # type: ignore[attr-defined]
    with pytest.raises(error, match="unsupported PostgreSQL DSN"):
        module._postgres_environment(  # type: ignore[attr-defined]
            "postgresql://u:p@db/request_engine?unknown=value"
        )


def test_offsite_command_requires_artifact_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    error = cast(type[RuntimeError], module.RecoveryBundleError)  # type: ignore[attr-defined]
    monkeypatch.setattr(module, "_run", lambda command, env=None: None)
    with pytest.raises(error, match="artifact"):
        module._copy_offsite(tmp_path / "bundle.age", "rclone copy remote:path")  # type: ignore[attr-defined]


def test_restore_fails_closed_without_outbound_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    error = cast(type[RuntimeError], module.RecoveryBundleError)  # type: ignore[attr-defined]
    monkeypatch.delenv("REQUEST_ENGINE_OUTBOUND_FENCED", raising=False)
    with pytest.raises(error, match="OUTBOUND_FENCED"):
        module._require_restore_fence()  # type: ignore[attr-defined]


def test_bundle_verification_rejects_tampered_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    error = cast(type[RuntimeError], module.RecoveryBundleError)  # type: ignore[attr-defined]
    source = tmp_path / "source"
    source.mkdir()
    (source / "postgres.dump").write_bytes(b"postgres-original")
    (source / "openbao.snap").write_bytes(b"openbao-original")
    module._write_manifest(source)  # type: ignore[attr-defined]

    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in ("manifest.json", "postgres.dump", "openbao.snap"):
            bundle.add(source / name, arcname=name)
    (source / "postgres.dump").write_bytes(b"tampered")
    with tarfile.open(archive, "w:gz") as bundle:
        for name in ("manifest.json", "postgres.dump", "openbao.snap"):
            bundle.add(source / name, arcname=name)

    monkeypatch.setattr(
        module,
        "_decrypt",
        lambda bundle, output, identity: output.write_bytes(archive.read_bytes()),
    )
    with pytest.raises(error, match="checksum mismatch"):
        module._extract_verified(  # type: ignore[attr-defined]
            tmp_path / "fake.age",
            tmp_path / "identity.txt",
            tmp_path / "verify",
        )


def test_restore_uses_standard_openbao_restore_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    bundle = tmp_path / "bundle.age"
    bundle.write_bytes(b"encrypted")
    identity = tmp_path / "identity.txt"
    identity.write_text("AGE-SECRET-KEY-TEST\n", encoding="utf-8")
    monkeypatch.setenv("REQUEST_ENGINE_OUTBOUND_FENCED", "true")
    monkeypatch.setenv(
        "REQUEST_ENGINE_RESTORE_DATABASE_URL",
        "postgresql://restore-user:restore-pass@db/request_engine",
    )
    monkeypatch.setenv("REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE", str(identity))
    monkeypatch.setattr(module, "_require_program", lambda name: name)

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, env: dict[str, str] | None = None) -> None:
        del env
        calls.append(command)

    monkeypatch.setattr(module, "_run", fake_run)

    def fake_extract(
        bundle_path: Path,
        identity_path: Path,
        root: Path,
    ) -> dict[str, object]:
        del bundle_path, identity_path
        extracted = root / "extracted"
        extracted.mkdir()
        (extracted / "postgres.dump").write_bytes(b"pg")
        (extracted / "openbao.snap").write_bytes(b"bao")
        return {"schema": "request-engine/recovery-bundle/v1"}

    monkeypatch.setattr(module, "_extract_verified", fake_extract)
    module.restore_backup(  # type: ignore[attr-defined]
        Namespace(
            bundle=str(bundle),
            postgres_dsn_env="REQUEST_ENGINE_RESTORE_DATABASE_URL",
            bao_command="bao",
            age_identity_file_env="REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE",
            confirm_destructive=True,
        )
    )
    assert calls[0][0] == "pg_restore"
    assert calls[1][:5] == ["bao", "operator", "raft", "snapshot", "restore"]
    assert "-force" not in calls[1]


def test_manifest_contains_only_expected_recovery_files(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "postgres.dump").write_bytes(b"pg")
    (tmp_path / "openbao.snap").write_bytes(b"bao")
    manifest_path = module._write_manifest(tmp_path)  # type: ignore[attr-defined]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {item["name"] for item in manifest["files"]} == {
        "postgres.dump",
        "openbao.snap",
    }
    assert "password" not in manifest_path.read_text(encoding="utf-8").lower()
