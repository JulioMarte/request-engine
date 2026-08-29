from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tests" / "e2e" / "world_clock.py"
SD = ZoneInfo("America/Santo_Domingo")


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


def test_morning_world_anchors_five_minutes_ahead() -> None:
    world_clock = _load_world_clock_module()
    anchor = world_clock.anchor_for(datetime(2026, 8, 28, 9, 0, tzinfo=SD))

    assert anchor == datetime(2026, 8, 28, 9, 5, tzinfo=SD)


def test_evening_world_keeps_same_local_day() -> None:
    world_clock = _load_world_clock_module()
    anchor = world_clock.anchor_for(datetime(2026, 8, 28, 21, 59, tzinfo=SD))

    assert anchor == datetime(2026, 8, 28, 22, 4, tzinfo=SD)


def test_late_evening_world_anchors_next_local_day() -> None:
    world_clock = _load_world_clock_module()
    anchor = world_clock.anchor_for(datetime(2026, 8, 28, 23, 30, tzinfo=SD))

    assert anchor == datetime(2026, 8, 29, 0, 5, tzinfo=SD)


def test_anchor_boundary_flips_at_22_local() -> None:
    world_clock = _load_world_clock_module()
    before = world_clock.anchor_for(datetime(2026, 8, 28, 21, 59, 59, tzinfo=SD))
    at_boundary = world_clock.anchor_for(datetime(2026, 8, 28, 22, 0, 0, tzinfo=SD))

    assert before == datetime(2026, 8, 28, 22, 4, 59, tzinfo=SD)
    assert at_boundary == datetime(2026, 8, 29, 0, 5, tzinfo=SD)
