from __future__ import annotations

import ast
import runpy
from pathlib import Path
from typing import Any, cast

from request_engine.platform.security.capabilities import CAPABILITIES
from scripts.release.v3_public_api_contract_baseline import (
    EXPECTED_CAPABILITIES,
    EXPECTED_LITERAL_ERROR_CODES,
    EXPECTED_OPERATIONS,
    EXPECTED_REQUEST_HELPER_CODES,
    EXPECTED_SHARED_ERROR_CODES,
)

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


def test_v3_public_http_operation_surface_is_frozen() -> None:
    actual = tuple(
        "|".join(
            (
                operation.name,
                operation.method,
                operation.path_template,
                operation.capability or "",
            )
        )
        for operation in _public_operations()
    )
    assert actual == EXPECTED_OPERATIONS


def test_v3_capability_registry_is_frozen() -> None:
    actual = tuple(
        "|".join(
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
        for definition in CAPABILITIES
    )
    assert actual == EXPECTED_CAPABILITIES
    assert all(definition.schema_version == 1 for definition in CAPABILITIES)


def test_v3_public_error_code_inventory_is_frozen() -> None:
    literal_codes: set[str] = set()
    for path in _ERROR_MODULES:
        literal_codes |= _literal_error_codes(path)
    assert literal_codes == EXPECTED_LITERAL_ERROR_CODES

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


def test_v3_operation_capabilities_are_classified() -> None:
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
