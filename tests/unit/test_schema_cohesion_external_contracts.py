from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "analyze_schema_cohesion.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schema_cohesion_contracts_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _view(schema: str, name: str) -> dict[str, object]:
    return {
        "schema_name": schema,
        "relation_name": name,
        "relation_kind": "v",
        "definition": "SELECT 1",
        "owner": "request_engine_schema_owner",
        "row_security": False,
        "force_row_security": False,
        "is_partition": False,
    }


def test_documented_operator_view_is_not_an_orphan_candidate() -> None:
    module = _load()
    catalog: dict[str, object] = {
        "relations": [
            _view("request_admin", "worker_dead_letters_v1"),
            _view("request_admin", "unsupported_health_v1"),
        ],
        "view_dependencies": [],
        "routines": [],
        "indexes": [],
        "triggers": [],
        "policies": [],
        "constraints": [],
        "table_grants": [],
        "column_grants": [],
        "routine_grants": [],
    }

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["external_contract_views"] == ["request_admin.worker_dead_letters_v1"]
    assert result["orphan_view_candidates"] == ["request_admin.unsupported_health_v1"]
    assert result["zero_production_reference_views"] == [
        "request_admin.unsupported_health_v1",
        "request_admin.worker_dead_letters_v1",
    ]
