from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tests" / "e2e" / "world_clock.py"


def _load_world_clock_module() -> ModuleType:
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        spec = importlib.util.spec_from_file_location("e2e.world_clock", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT / "tests"))
    assert isinstance(module, ModuleType)
    return module


def test_daytime_world_keeps_the_repository_default_timezone() -> None:
    world_clock = _load_world_clock_module()

    assert world_clock.pick_business_timezone(datetime(2026, 8, 29, 14, 0, tzinfo=UTC)) == (
        "America/Santo_Domingo"
    )


def test_evening_world_keeps_the_repository_default_timezone() -> None:
    world_clock = _load_world_clock_module()

    assert world_clock.pick_business_timezone(datetime(2026, 8, 29, 21, 0, tzinfo=UTC)) == (
        "America/Santo_Domingo"
    )


def test_late_evening_world_configures_a_runway_timezone() -> None:
    world_clock = _load_world_clock_module()
    picked = world_clock.pick_business_timezone(datetime(2026, 8, 30, 3, 0, tzinfo=UTC))

    assert picked == "Asia/Tokyo"


def test_early_morning_world_configures_a_runway_timezone() -> None:
    world_clock = _load_world_clock_module()

    assert (
        world_clock.pick_business_timezone(datetime(2026, 8, 29, 3, 0, tzinfo=UTC)) == "Asia/Tokyo"
    )
