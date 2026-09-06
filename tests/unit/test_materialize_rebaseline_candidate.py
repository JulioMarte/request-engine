from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "materialize_rebaseline_candidate.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rebaseline_materializer_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, bytes, bytes]:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    schema = b"first line\nsecond line\nthird line\n"
    roles = b"CREATE ROLE example NOLOGIN;\n"
    (artifact_dir / "schema.sql").write_bytes(schema)
    (artifact_dir / "roles.sql").write_bytes(roles)

    first = schema[:11]
    second = schema[11:]
    manifest = {
        "schema_version": 1,
        "schema_payload": {
            "source_artifact_name": "schema.sql",
            "bytes": len(schema),
            "sha256": _sha256(schema),
            "materialized_parts": [
                {
                    "path": "0001_schema.01.sql",
                    "bytes": len(first),
                    "sha256": _sha256(first),
                },
                {
                    "path": "0001_schema.02.sql",
                    "bytes": len(second),
                    "sha256": _sha256(second),
                },
            ],
        },
        "role_bootstrap": {
            "source_artifact_name": "roles.sql",
            "path": "0001_roles.sql",
            "bytes": len(roles),
            "sha256": _sha256(roles),
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return artifact_dir, manifest_path, schema, roles


def test_materializer_reconstructs_only_manifested_candidate(tmp_path: Path) -> None:
    module = _load()
    artifact_dir, manifest_path, schema, roles = _write_fixture(tmp_path)
    output_dir = tmp_path / "output"

    module.materialize(
        artifact_dir=artifact_dir,
        output_dir=output_dir,
        manifest_path=manifest_path,
    )

    reconstructed = b"".join(
        (output_dir / name).read_bytes()
        for name in ("0001_schema.01.sql", "0001_schema.02.sql")
    )
    assert reconstructed == schema
    assert (output_dir / "0001_roles.sql").read_bytes() == roles


def test_materializer_rejects_same_size_mutated_artifact(tmp_path: Path) -> None:
    module = _load()
    artifact_dir, manifest_path, schema, _ = _write_fixture(tmp_path)
    mutated = bytearray(schema)
    mutated[0] = ord("F")
    assert len(mutated) == len(schema)
    (artifact_dir / "schema.sql").write_bytes(mutated)

    with pytest.raises(RuntimeError, match="expected sha256"):
        module.materialize(
            artifact_dir=artifact_dir,
            output_dir=tmp_path / "output",
            manifest_path=manifest_path,
        )
