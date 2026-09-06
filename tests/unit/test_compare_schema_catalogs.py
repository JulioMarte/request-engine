from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "db" / "compare_schema_catalogs.py"
_SPEC = importlib.util.spec_from_file_location("compare_schema_catalogs", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load compare_schema_catalogs.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
compare = cast(Callable[[dict[str, Any], dict[str, Any]], dict[str, object]], _MODULE.compare)


def _column(name: str, ordinal: int) -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": "resources",
        "column_name": name,
        "ordinal": ordinal,
        "data_type": "uuid",
        "not_null": True,
    }


def test_compare_ignores_only_historical_attnum_gaps() -> None:
    expected = {
        "columns": [
            _column("id", 1),
            _column("resource_key", 4),
            _column("organization_id", 5),
        ]
    }
    actual = {
        "columns": [
            _column("id", 1),
            _column("resource_key", 2),
            _column("organization_id", 3),
        ]
    }

    assert compare(expected, actual)["equivalent"] is True


def test_compare_rejects_surviving_column_reordering() -> None:
    expected = {
        "columns": [
            _column("id", 1),
            _column("resource_key", 4),
            _column("organization_id", 5),
        ]
    }
    actual = {
        "columns": [
            _column("id", 1),
            _column("organization_id", 2),
            _column("resource_key", 3),
        ]
    }

    result = compare(expected, actual)

    assert result["equivalent"] is False
    assert result["first_difference"] == {
        "section": "columns",
        "kind": "value_mismatch",
        "index": 1,
        "expected": _column("resource_key", 2),
        "actual": _column("organization_id", 2),
    }
