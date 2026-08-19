from __future__ import annotations

import argparse
import ast
import hashlib
import json
import runpy
from pathlib import Path
from typing import Any, cast

from fastapi import Request

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.capabilities import CAPABILITIES, capability_definition
from request_engine.platform.security.context import ActorContext

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
_SIGNING_KEY = b"request-engine-v3-public-contract-proof"


class RejectAllResolver:
    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        raise AuthenticationRequired


def _public_operations() -> tuple[Any, ...]:
    namespace = runpy.run_path("tests/e2e/http_surface.py")
    return cast(tuple[Any, ...], namespace["PUBLIC_HTTP_OPERATIONS"])


def _operation_lines(operations: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(
        "|".join(
            (
                operation.name,
                operation.method,
                operation.path_template,
                operation.capability or "",
            )
        )
        for operation in operations
    )


def _capability_lines() -> tuple[str, ...]:
    return tuple(
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


def _error_snapshot() -> tuple[set[str], set[str], set[str]]:
    literal_codes: set[str] = set()
    for path in _ERROR_MODULES:
        literal_codes |= _literal_error_codes(path)

    shared_text = Path("src/request_engine/entrypoints/http/errors.py").read_text(encoding="utf-8")
    shared_codes = {
        code for code in EXPECTED_SHARED_ERROR_CODES if f'code = "{code}"' in shared_text
    }
    request_text = Path("src/request_engine/modules/requests/api/errors.py").read_text(
        encoding="utf-8"
    )
    helper_codes = {
        code for code in EXPECTED_REQUEST_HELPER_CODES if f'_conflict("{code}"' in request_text
    }
    return literal_codes, shared_codes, helper_codes


def _operation_contract(openapi: dict[str, object], *, path: str, method: str) -> dict[str, object]:
    paths_value = openapi.get("paths")
    assert isinstance(paths_value, dict)
    path_value = cast(dict[str, object], paths_value)[path]
    assert isinstance(path_value, dict)
    operation_value = cast(dict[str, object], path_value)[method.lower()]
    assert isinstance(operation_value, dict)
    return cast(dict[str, object], operation_value)


def _openapi_snapshot(operations: tuple[Any, ...]) -> tuple[list[dict[str, object]], list[str]]:
    session_factory = cast(SessionFactory, object())
    app = create_app(
        session_factory=session_factory,
        actor_resolver=RejectAllResolver(),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    openapi = cast(dict[str, object], app.openapi())
    snapshot: list[dict[str, object]] = []
    errors: list[str] = []
    for operation in operations:
        contract = _operation_contract(
            openapi, path=operation.path_template, method=operation.method
        )
        item: dict[str, object] = {
            "name": operation.name,
            "method": operation.method,
            "path": operation.path_template,
            "operation_id": contract.get("operationId"),
        }
        if operation.capability is None:
            if operation.name != "capabilities.list":
                errors.append(f"{operation.name}: unexpected capability-less operation")
            snapshot.append(item)
            continue

        definition = capability_definition(operation.capability)
        if definition is None:
            errors.append(f"{operation.name}: capability definition is missing")
            snapshot.append(item)
            continue

        expected_metadata: dict[str, object] = {
            "x-request-engine-capability": definition.key,
            "x-request-engine-schema-version": definition.schema_version,
            "x-request-engine-idempotency": definition.idempotency.value,
            "x-request-engine-expected-revision": definition.revision.value,
            "x-request-engine-exposure": definition.exposure.value,
        }
        if definition.party_scope is not None:
            expected_metadata["x-request-engine-party-scope"] = definition.party_scope
        if definition.override_capability is not None:
            expected_metadata["x-request-engine-override-capability"] = (
                definition.override_capability
            )

        expected_operation_id = definition.key.replace(".", "_")
        if contract.get("operationId") != expected_operation_id:
            errors.append(f"{operation.name}: operationId does not match capability key")
        for key, expected_value in expected_metadata.items():
            if contract.get(key) != expected_value:
                errors.append(f"{operation.name}: {key} does not match capability definition")
        for optional_key in (
            "x-request-engine-party-scope",
            "x-request-engine-override-capability",
        ):
            if optional_key not in expected_metadata and optional_key in contract:
                errors.append(f"{operation.name}: unexpected {optional_key}")

        item["capability"] = definition.key
        item["metadata"] = expected_metadata
        snapshot.append(item)
    return snapshot, errors


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_report() -> dict[str, object]:
    operations = _public_operations()
    operation_lines = _operation_lines(operations)
    capability_lines = _capability_lines()
    literal_codes, shared_codes, helper_codes = _error_snapshot()
    openapi_snapshot, openapi_errors = _openapi_snapshot(operations)

    failures = list(openapi_errors)
    if operation_lines != EXPECTED_OPERATIONS:
        failures.append("public HTTP operation baseline mismatch")
    if capability_lines != EXPECTED_CAPABILITIES:
        failures.append("capability registry baseline mismatch")
    if literal_codes != EXPECTED_LITERAL_ERROR_CODES:
        failures.append("literal public error-code baseline mismatch")
    if shared_codes != EXPECTED_SHARED_ERROR_CODES:
        failures.append("shared HTTP error-code baseline mismatch")
    if helper_codes != EXPECTED_REQUEST_HELPER_CODES:
        failures.append("Request helper error-code baseline mismatch")
    if any(definition.schema_version != 1 for definition in CAPABILITIES):
        failures.append("one or more capability schema versions are not 1")

    contract = {
        "operations": list(operation_lines),
        "capabilities": list(capability_lines),
        "literal_error_codes": sorted(literal_codes),
        "shared_error_codes": sorted(shared_codes),
        "request_helper_error_codes": sorted(helper_codes),
        "openapi": openapi_snapshot,
    }
    baseline = {
        "operations": list(EXPECTED_OPERATIONS),
        "capabilities": list(EXPECTED_CAPABILITIES),
        "literal_error_codes": sorted(EXPECTED_LITERAL_ERROR_CODES),
        "shared_error_codes": sorted(EXPECTED_SHARED_ERROR_CODES),
        "request_helper_error_codes": sorted(EXPECTED_REQUEST_HELPER_CODES),
    }
    schema_versions = sorted({definition.schema_version for definition in CAPABILITIES})
    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "operation_count": len(operation_lines),
        "capability_count": len(capability_lines),
        "capability_schema_versions": schema_versions,
        "error_code_count": len(literal_codes | shared_codes | helper_codes),
        "baseline_sha256": _fingerprint(baseline),
        "contract_sha256": _fingerprint(contract),
        "contract": contract,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    if report["status"] != "PASS":
        failures = cast(list[str], report["failures"])
        raise SystemExit("V3 public API contract proof failed: " + "; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
