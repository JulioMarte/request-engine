from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/release/validate_v3_invariant_registry.py"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("v3_invariant_registry_validator", VALIDATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_invariant_proof_registry_is_complete_and_owner_bound() -> None:
    validator = _load_validator()
    assert validator.validate_registry() == []
