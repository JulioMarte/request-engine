from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "build_architecture_diff.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("architecture_diff_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(symbols: list[str]) -> dict[str, object]:
    return {
        "modules": [
            {
                "module": "consumer",
                "fan_in": 0,
                "fan_out": 1,
                "inbound_modules": [],
                "outbound_modules": ["provider"],
            },
            {
                "module": "provider",
                "fan_in": 1,
                "fan_out": 0,
                "inbound_modules": ["consumer"],
                "outbound_modules": [],
            },
        ],
        "edges": [
            {
                "source": "consumer",
                "target": "provider",
                "contract_symbol_count": len(symbols),
                "contract_symbols": symbols,
            }
        ],
    }


def test_contract_growth_is_visible_even_when_fan_out_is_unchanged() -> None:
    module = _load()
    coupling_diff = cast(
        Callable[[dict[str, object], dict[str, object]], dict[str, object]],
        module._coupling_diff,
    )
    result = coupling_diff(_snapshot(["Read"]), _snapshot(["Read", "Command", "View"]))
    assert result["added_edges"] == []
    deltas = cast(list[dict[str, object]], result["contract_usage_deltas"])
    assert deltas == [
        {
            "source": "consumer",
            "target": "provider",
            "before_symbol_count": 1,
            "after_symbol_count": 3,
            "added_contract_symbols": ["Command", "View"],
            "removed_contract_symbols": [],
            "interpretation": "none",
        }
    ]


def test_new_edge_and_contract_width_are_reported_separately() -> None:
    module = _load()
    coupling_diff = cast(
        Callable[[dict[str, object], dict[str, object]], dict[str, object]],
        module._coupling_diff,
    )
    base = {"modules": [], "edges": []}
    result = coupling_diff(base, _snapshot(["Read", "Command"]))
    assert result["added_edges"] == [{"source": "consumer", "target": "provider"}]
    deltas = cast(list[dict[str, object]], result["contract_usage_deltas"])
    assert deltas[0]["before_symbol_count"] == 0
    assert deltas[0]["after_symbol_count"] == 2


def test_architecture_diff_summary_explicitly_rejects_synthetic_score() -> None:
    module = _load()
    render = cast(Callable[[dict[str, object]], str], module.render_summary)
    payload: dict[str, Any] = {
        "provenance": {
            "source_head_sha": "a" * 40,
            "tested_sha": "b" * 40,
            "test_mode": "PR_INTEGRATION_CANDIDATE",
        },
        "module_coupling": {
            "added_edges": [],
            "removed_edges": [],
            "contract_usage_deltas": [],
        },
        "suppressions": {"delta": 0},
        "navigation": [],
    }
    text = render(payload)
    assert "No architecture score is computed" in text
    assert "Source head" in text
    assert "Tested tree" in text
