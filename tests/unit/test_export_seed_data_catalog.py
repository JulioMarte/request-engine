from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "export_seed_data_catalog.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_catalog_exporter", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_install_identity_fields_are_normalized_but_relationship_is_preserved() -> None:
    module = _load()
    native = json.dumps({
        "id": "11111111-1111-1111-1111-111111111111",
        "kind": "native",
        "issuer_or_environment": "request-engine-native",
        "status": "active",
        "configuration_ref": None,
        "revision": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    instance = json.dumps({
        "singleton_key": 1,
        "id": "33333333-3333-3333-3333-333333333333",
        "state": "unclaimed",
        "revision": 1,
        "built_in_native_authority_id": "11111111-1111-1111-1111-111111111111",
        "built_in_workload_authority_id": "22222222-2222-2222-2222-222222222222",
        "created_at": "2026-01-01T00:00:01+00:00",
        "claimed_at": None,
        "initial_owner_principal_id": None,
        "claim_provenance": None,
    })
    normalized_native = json.loads(
        module._normalize_seed_row("request_engine", "identity_authorities", native)
    )
    normalized_instance = json.loads(
        module._normalize_seed_row("request_engine", "platform_instance", instance)
    )
    assert normalized_native["id"] == "<generated:built-in-native-authority-id>"
    assert normalized_instance["id"] == "<generated:platform-instance-id>"
    assert normalized_instance["built_in_native_authority_id"] == normalized_native["id"]
    assert normalized_instance["built_in_workload_authority_id"] == (
        "<generated:built-in-workload-authority-id>"
    )


def test_unrelated_seed_rows_remain_exact() -> None:
    module = _load()
    raw = '{"policy_key":"platform-owner-v3","revision":3}'
    assert module._normalize_seed_row(
        "request_engine", "platform_owner_policies", raw
    ) == raw
