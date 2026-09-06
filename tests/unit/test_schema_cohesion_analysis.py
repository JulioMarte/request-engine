from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "analyze_schema_cohesion.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schema_cohesion_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routine(
    name: str,
    *,
    arguments: str = "",
    body: str = "BEGIN RETURN NEW; END",
    security_definer: bool = True,
) -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "routine_name": name,
        "identity_arguments": arguments,
        "routine_kind": "f",
        "owner": "request_engine_schema_owner",
        "security_definer": security_definer,
        "volatility": "v",
        "configuration": ["search_path=pg_catalog, request_engine, pg_temp"],
        "definition": (
            f"CREATE OR REPLACE FUNCTION request_engine.{name}({arguments})\n"
            " RETURNS trigger\n"
            " LANGUAGE plpgsql\n"
            f"AS $function$\n{body}\n$function$\n"
        ),
    }


def _index(name: str, *, primary: bool = False, column: str = "value") -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": "sample",
        "index_name": name,
        "is_unique": False,
        "is_primary": primary,
        "is_valid": True,
        "definition": f"CREATE INDEX {name} ON request_engine.sample USING btree ({column})",
    }


def _catalog() -> dict[str, object]:
    return {
        "relations": [],
        "view_dependencies": [],
        "routines": [],
        "indexes": [],
        "triggers": [],
    }


def test_routine_duplicates_ignore_name_but_preserve_contract() -> None:
    module = _load()
    catalog = _catalog()
    catalog["routines"] = [
        _routine("first"),
        _routine("second"),
        _routine("different_arguments", arguments="value uuid"),
        _routine("different_security", security_definer=False),
        _routine("different_body", body="BEGIN RETURN OLD; END"),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["exact_routine_implementation_duplicates"] == [
        ["request_engine.first()", "request_engine.second()"]
    ]


def test_index_duplicates_ignore_only_index_name() -> None:
    module = _load()
    catalog = _catalog()
    catalog["indexes"] = [
        _index("sample_value_a"),
        _index("sample_value_b"),
        _index("sample_other", column="other"),
        _index("sample_primary_shape", primary=True),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["exact_index_definition_duplicates"] == [
        [
            "request_engine.sample.sample_value_a",
            "request_engine.sample.sample_value_b",
        ]
    ]


def test_unreferenced_trigger_routines_are_review_candidates() -> None:
    module = _load()
    catalog = _catalog()
    catalog["routines"] = [_routine("used"), _routine("unused")]
    catalog["triggers"] = [
        {
            "schema_name": "request_engine",
            "relation_name": "sample",
            "trigger_name": "sample_used",
            "enabled": "O",
            "definition": (
                "CREATE TRIGGER sample_used AFTER UPDATE ON request_engine.sample "
                "FOR EACH ROW EXECUTE FUNCTION request_engine.used()"
            ),
        }
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["trigger_routine_count"] == 2
    assert result["referenced_trigger_routine_count"] == 1
    assert result["unreferenced_trigger_routines"] == ["request_engine.unused()"]
