from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "verify_accepted_baseline.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("accepted_baseline_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    role = {
        "role_name": "request_engine_app",
        "superuser": False,
        "inherit": True,
        "create_role": False,
        "create_db": False,
        "can_login": False,
        "replication": False,
        "bypass_rls": False,
        "connection_limit": -1,
        "valid_until": None,
        "has_password": False,
    }
    role_contract = {key: value for key, value in role.items() if key != "role_name"}
    manifest = {
        "effective_model": {
            "relations": 2,
            "tables": 1,
            "views": 1,
            "columns": 3,
            "constraints": 2,
            "indexes": 1,
            "routines": 1,
            "triggers": 1,
            "policies": 1,
            "roles": 1,
            "role_memberships": 0,
            "column_grants": 0,
        },
        "role_bootstrap": {
            "expected_roles": {"request_engine_app": role_contract},
            "role_memberships": [],
            "role_settings": [],
        },
    }
    schema_catalog = {
        "counts": {
            "relations": 2,
            "columns": 3,
            "constraints": 2,
            "indexes": 1,
            "routines": 1,
            "triggers": 1,
            "policies": 1,
            "column_grants": 0,
        },
        "relations": [
            {"relation_kind": "r", "schema_name": "request_engine", "relation_name": "items"},
            {"relation_kind": "v", "schema_name": "request_read", "relation_name": "items_v1"},
        ],
    }
    role_catalog = {
        "counts": {"roles": 1, "role_memberships": 0, "role_settings": 0},
        "roles": [role],
        "role_memberships": [],
        "role_settings": [],
    }
    return manifest, schema_catalog, role_catalog, {}


def test_verifier_accepts_exact_manifested_baseline() -> None:
    module = _load()
    manifest, schema_catalog, role_catalog, analysis = _inputs()

    result = module.verify(
        manifest=manifest,
        schema_catalog=schema_catalog,
        role_catalog=role_catalog,
        analysis=analysis,
    )

    assert result["schema_equivalent"] is True
    assert result["role_equivalent"] is True
    assert result["effective_model"] == manifest["effective_model"]


def test_verifier_rejects_schema_count_drift() -> None:
    module = _load()
    manifest, schema_catalog, role_catalog, analysis = _inputs()
    schema_catalog["counts"]["indexes"] = 2

    with pytest.raises(RuntimeError, match="effective-model counts drifted"):
        module.verify(
            manifest=manifest,
            schema_catalog=schema_catalog,
            role_catalog=role_catalog,
            analysis=analysis,
        )


def test_verifier_rejects_new_analyzer_finding() -> None:
    module = _load()
    manifest, schema_catalog, role_catalog, analysis = _inputs()
    analysis["public_grants"] = [{"grantee": "PUBLIC"}]

    with pytest.raises(RuntimeError, match="cohesion findings"):
        module.verify(
            manifest=manifest,
            schema_catalog=schema_catalog,
            role_catalog=role_catalog,
            analysis=analysis,
        )
