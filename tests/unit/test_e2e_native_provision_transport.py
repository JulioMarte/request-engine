"""Transport-only regression: black-box native provisioning preserves command intent keys."""

import ast
import json
import runpy
import sys
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/system_e2e/runner.py"
pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_native_provision_command_sends_same_key_and_body_on_transport_retry() -> None:
    with patch.object(sys, "path", [str(ROOT / "tests/fixtures"), *sys.path]):
        runner = runpy.run_path(str(RUNNER))
    response = Mock(status=201)
    response.read.return_value = b'{"native_identity_id":"transport-fixture-id"}'
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=context) as transport:
        for _ in range(2):
            result = runner["_native_identity"](
                "https://control.example",
                "operator@example.test",
                "transport-fixture-password",
                bearer="transport-fixture-bearer",
                idempotency_key="operator-provision-intent-1",
            )
            assert result == "transport-fixture-id"
    requests = [cast(Request, call.args[0]) for call in transport.call_args_list]
    assert len(requests) == 2
    for request in requests:
        assert request.full_url == "https://control.example/v1/platform/native-identities"
        assert request.method == "POST"
        assert request.get_header("Idempotency-key") == "operator-provision-intent-1"
        assert request.get_header("Authorization") == "Bearer transport-fixture-bearer"
        assert isinstance(request.data, bytes)
        assert json.loads(request.data) == {
            "login_handle": "operator@example.test",
            "password": "transport-fixture-password",
        }
    assert requests[0].data == requests[1].data


def test_every_suite_native_provision_intent_supplies_a_distinct_explicit_key() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id != "_native_identity":
            continue
        key = next((value.value for value in call.keywords if value.arg == "idempotency_key"), None)
        assert isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value
        assert key.value not in keys, "different provisioning intents must not reuse one key"
        keys.add(key.value)
    assert keys, "the canonical suite must exercise governed native provisioning"
