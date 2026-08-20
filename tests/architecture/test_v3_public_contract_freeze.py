from __future__ import annotations

import ast
import runpy
from pathlib import Path
from typing import Any, cast

from request_engine.platform.security.capabilities import CAPABILITIES

_BASELINE = runpy.run_path("scripts/release/v3_public_api_contract_baseline.py")
EXPECTED_OPERATIONS = cast(tuple[str, ...], _BASELINE["EXPECTED_OPERATIONS"])
EXPECTED_CAPABILITIES = cast(tuple[str, ...], _BASELINE["EXPECTED_CAPABILITIES"])
EXPECTED_LITERAL_ERROR_CODES = cast(frozenset[str], _BASELINE["EXPECTED_LITERAL_ERROR_CODES"])
EXPECTED_SHARED_ERROR_CODES = cast(frozenset[str], _BASELINE["EXPECTED_SHARED_ERROR_CODES"])
EXPECTED_REQUEST_HELPER_CODES = cast(frozenset[str], _BASELINE["EXPECTED_REQUEST_HELPER_CODES"])

_ERROR_MODULES = (
    Path("src/request_engine/entrypoints/http/errors.py"),
    Path("src/request_engine/modules/booking/api/errors.py"),
    Path("src/request_engine/modules/queue/api/errors.py"),
    Path("src/request_engine/modules/communications/api/errors.py"),
    Path("src/request_engine/modules/requests/api/errors.py"),
)


def _public_operations() -> tuple[Any, ...]:
    namespace = runpy.run_path("tests/e2e/http_surface.py")
    return cast(tuple[Any, ...], namespace["PUBLIC_HTTP_OPERATIONS"])


def _literal_error_codes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "ErrorBody":
            continue
        for keyword in node.keywords:
            if keyword.arg != "code":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                codes.add(value.value)
    return codes


def _operation_line(operation: Any) -> str:
    return "|".join(
        (
            operation.name,
            operation.method,
            operation.path_template,
            operation.capability or "",
        )
    )


def _capability_line(definition: Any) -> str:
    return "|".join(
        (
            definition.key,
            definition.exposure.value,
            definition.kind.value,
            definition.idempotency.value,
            definition.revision.value,
            definition.party_scope or "",
            definition.override_capability or "",
            ",".join(sorted(definition.legacy_aliases)),
            "1" if definition.runtime_available else "0",
        )
    )


def test_released_v3_public_http_operations_remain_compatible() -> None:
    actual = {_operation_line(operation) for operation in _public_operations()}
    assert set(EXPECTED_OPERATIONS) <= actual


def test_released_v3_capabilities_remain_compatible() -> None:
    actual = {_capability_line(definition) for definition in CAPABILITIES}
    assert set(EXPECTED_CAPABILITIES) <= actual
    assert all(definition.schema_version >= 1 for definition in CAPABILITIES)


def test_released_v3_public_error_codes_remain_available() -> None:
    literal_codes: set[str] = set()
    for path in _ERROR_MODULES:
        literal_codes |= _literal_error_codes(path)
    assert EXPECTED_LITERAL_ERROR_CODES <= literal_codes

    shared_errors = Path("src/request_engine/entrypoints/http/errors.py").read_text(
        encoding="utf-8"
    )
    for code in EXPECTED_SHARED_ERROR_CODES:
        assert f'code = "{code}"' in shared_errors

    request_errors = Path("src/request_engine/modules/requests/api/errors.py").read_text(
        encoding="utf-8"
    )
    for code in EXPECTED_REQUEST_HELPER_CODES:
        assert f'_conflict("{code}"' in request_errors


def test_current_operation_capabilities_are_classified() -> None:
    definitions = {definition.key: definition for definition in CAPABILITIES}
    for operation in _public_operations():
        if operation.capability is None:
            assert operation.name == "capabilities.list"
            continue
        definition = definitions[operation.capability]
        assert definition.runtime_available
        assert definition.exposure.value in {"public", "operator"}
        requires_idempotency = definition.idempotency.value == "required"
        assert requires_idempotency is operation.idempotency_required
        assert (definition.kind.value == "command") is operation.mutates
