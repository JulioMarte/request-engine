from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "migrations" / "baseline" / "loader.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("baseline_loader_under_test", LOADER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _baseline(tmp_path: Path, parts: list[bytes]) -> Path:
    materialized_parts: list[dict[str, object]] = []
    for index, payload in enumerate(parts, start=1):
        name = f"0001_schema.{index:02d}.sql"
        (tmp_path / name).write_bytes(payload)
        materialized_parts.append({"path": name, "bytes": len(payload), "sha256": _sha256(payload)})
    combined = b"".join(parts)
    manifest = {
        "schema_version": 1,
        "schema_payload": {
            "bytes": len(combined),
            "sha256": _sha256(combined),
            "materialized_parts": materialized_parts,
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def _point_loader_at(module: ModuleType, baseline: Path) -> None:
    module.__dict__["ROOT"] = baseline
    module.__dict__["MANIFEST_PATH"] = baseline / "manifest.json"


def test_baseline_loader_reconstructs_manifested_sql(tmp_path: Path) -> None:
    module = _load()
    baseline = _baseline(tmp_path, [b"SELECT 1;\n", b"SELECT 2;\n"])
    _point_loader_at(module, baseline)

    assert module.load_schema_sql() == "SELECT 1;\nSELECT 2;\n"


def test_baseline_loader_rejects_mutated_part(tmp_path: Path) -> None:
    module = _load()
    baseline = _baseline(tmp_path, [b"SELECT 1;\n", b"SELECT 2;\n"])
    _point_loader_at(module, baseline)
    (baseline / "0001_schema.02.sql").write_bytes(b"SELECT 3;\n")

    with pytest.raises(RuntimeError, match="expected sha256"):
        module.load_schema_sql()


def test_baseline_loader_rejects_psql_meta_commands(tmp_path: Path) -> None:
    module = _load()
    baseline = _baseline(tmp_path, [b"SELECT 1;\n\\unrestrict token\n"])
    _point_loader_at(module, baseline)

    with pytest.raises(RuntimeError, match="psql meta-command"):
        module.load_schema_sql()


def _with_role_sql(baseline: Path, extension: bytes, audit: bytes) -> None:
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    entries = {}
    for name, payload in (
        ("0001_extension_roles.sql", extension),
        ("0001_post_install_audit.sql", audit),
    ):
        (baseline / name).write_bytes(payload)
        entries[name] = {"path": name, "bytes": len(payload), "sha256": _sha256(payload)}
    manifest["role_bootstrap"] = {
        "extension_roles": entries["0001_extension_roles.sql"],
        "post_install_audit": entries["0001_post_install_audit.sql"],
    }
    (baseline / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_baseline_loader_verifies_extension_role_and_audit_payloads(tmp_path: Path) -> None:
    module = _load()
    baseline = _baseline(tmp_path, [b"SELECT 1;\n"])
    _with_role_sql(baseline, b"DO $$ BEGIN END $$;\n", b"SELECT 2;\n")
    _point_loader_at(module, baseline)

    assert module.load_extension_role_sql() == "DO $$ BEGIN END $$;\n"
    assert module.load_post_install_audit_sql() == "SELECT 2;\n"

    (baseline / "0001_extension_roles.sql").write_bytes(b"CREATE ROLE x;\n    \n")
    with pytest.raises(RuntimeError, match="expected"):
        module.load_extension_role_sql()


def test_baseline_loader_rejects_meta_commands_in_audit_payload(tmp_path: Path) -> None:
    module = _load()
    baseline = _baseline(tmp_path, [b"SELECT 1;\n"])
    _with_role_sql(baseline, b"SELECT 1;\n", b"\\connect other\n")
    _point_loader_at(module, baseline)

    with pytest.raises(RuntimeError, match="psql meta-command"):
        module.load_post_install_audit_sql()
