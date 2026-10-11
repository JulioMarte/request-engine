"""OpenAPI-driven catalog of the control-plane operations the console projects.

The console renders and executes operations from canonical OpenAPI metadata; it
does not maintain a second hand-written registry. This keeps every control-plane
operation reachable (and testably so) instead of curating a partial menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
_MUTATING_METHODS = frozenset({"post", "put", "patch", "delete"})
_ANONYMOUS_AUTH_PATHS = frozenset(
    {
        "/auth/native/sessions",
        "/auth/native/webauthn/authentication-options",
        "/auth/native/webauthn/sessions",
        "/auth/native/password:request-recovery",
        "/auth/native/password:recover",
        "/auth/native/password:recover-with-code",
        "/auth/native/recovery-addresses:verify",
        "/v1/platform/owner-invitations:enroll",
    }
)


@dataclass(frozen=True)
class AdminParameter:
    name: str
    location: str
    required: bool
    schema: dict[str, Any]
    description: str


@dataclass(frozen=True)
class AdminOperation:
    operation_id: str
    method: str
    path_template: str
    summary: str
    description: str
    tags: tuple[str, ...]
    capability: str | None
    kind: str | None
    idempotency: str | None
    exposure: str | None
    owner: str | None
    tool_name: str | None
    tool_audiences: tuple[str, ...]
    auth_kind: str
    console_flow: str | None
    parameters: tuple[AdminParameter, ...]
    body_schema: dict[str, Any] | None

    @property
    def is_mutating(self) -> bool:
        return self.method.lower() in _MUTATING_METHODS

    @property
    def requires_idempotency_key(self) -> bool:
        if self.idempotency is not None and self.idempotency not in {"none", ""}:
            return True
        return self.capability is not None and self.is_mutating

    @property
    def is_platform_operation(self) -> bool:
        return self.capability is not None

    @property
    def group(self) -> str:
        if self.tags:
            return self.tags[0]
        if self.owner is not None:
            return self.owner
        return "other"


@dataclass(frozen=True)
class AdminCatalog:
    operations: tuple[AdminOperation, ...]

    def by_id(self) -> dict[str, AdminOperation]:
        return {operation.operation_id: operation for operation in self.operations}

    def groups(self) -> dict[str, tuple[AdminOperation, ...]]:
        grouped: dict[str, list[AdminOperation]] = {}
        for operation in self.operations:
            grouped.setdefault(operation.group, []).append(operation)
        return {
            name: tuple(sorted(items, key=lambda item: item.operation_id))
            for name, items in sorted(grouped.items())
        }

    def platform_operations(self) -> tuple[AdminOperation, ...]:
        return tuple(operation for operation in self.operations if operation.is_platform_operation)


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_str_tuple(value: object) -> tuple[str, ...]:
    return tuple(item for item in as_list(value) if isinstance(item, str))


def _as_schema(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return as_mapping(value)
    return None


class _SchemaResolver:
    """Resolve local ``$ref`` pointers so generic forms can read real properties."""

    def __init__(self, document: dict[str, Any]) -> None:
        components = as_mapping(document.get("components"))
        self._schemas: dict[str, Any] = as_mapping(components.get("schemas"))

    def resolve(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        return self._resolve(schema, frozenset())

    def _resolve(
        self, schema: dict[str, Any] | None, seen: frozenset[str]
    ) -> dict[str, Any] | None:
        if schema is None:
            return None
        reference = schema.get("$ref")
        if isinstance(reference, str):
            if reference in seen:
                return None
            name = reference.rsplit("/", 1)[-1]
            target = self._schemas.get(name)
            return self._resolve(_as_schema(target), seen | {reference})
        result: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                resolved_properties: dict[str, Any] = {}
                for prop_name, prop_schema in as_mapping(value).items():
                    resolved_properties[prop_name] = (
                        self._resolve(_as_schema(prop_schema), frozenset()) or {}
                    )
                result["properties"] = resolved_properties
            else:
                result[key] = value
        return result


def _auth_kind(path_template: str, method: str) -> str:
    if path_template.startswith("/v1/setup"):
        if path_template == "/v1/setup" and method == "get":
            return "anonymous"
        if path_template == "/v1/setup/sessions" and method == "post":
            return "anonymous"
        return "setup"
    if path_template in _ANONYMOUS_AUTH_PATHS:
        return "anonymous"
    return "bearer"


def _console_flow(path_template: str) -> str | None:
    if path_template.startswith("/v1/setup"):
        return "setup"
    if path_template.startswith("/auth/native"):
        return "auth"
    return None


def _extract_parameters(
    operation: dict[str, object], resolver: _SchemaResolver
) -> tuple[AdminParameter, ...]:
    raw = operation.get("parameters")
    if not isinstance(raw, list):
        return ()
    parameters: list[AdminParameter] = []
    for entry in cast(list[object], raw):
        if not isinstance(entry, dict):
            continue
        item = cast(dict[str, object], entry)
        name = _as_str(item.get("name"))
        location = _as_str(item.get("in"))
        if name is None or location is None:
            continue
        parameters.append(
            AdminParameter(
                name=name,
                location=location,
                required=item.get("required") is True,
                schema=resolver.resolve(_as_schema(item.get("schema"))) or {},
                description=_as_str(item.get("description")) or "",
            )
        )
    return tuple(parameters)


def _extract_body_schema(
    operation: dict[str, object], resolver: _SchemaResolver
) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = cast(dict[str, object], request_body).get("content")
    if not isinstance(content, dict):
        return None
    media = cast(dict[str, object], content)
    preferred = media.get("application/json")
    if preferred is None and media:
        preferred = next(iter(media.values()))
    if not isinstance(preferred, dict):
        return None
    return resolver.resolve(_as_schema(cast(dict[str, object], preferred).get("schema")))


def load_catalog(document: dict[str, Any]) -> AdminCatalog:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return AdminCatalog(operations=())
    resolver = _SchemaResolver(document)
    operations: list[AdminOperation] = []
    for path_template, path_item in cast(dict[str, object], paths).items():
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = cast(dict[str, object], path_item).get(method)
            if not isinstance(operation, dict):
                continue
            item = cast(dict[str, object], operation)
            operation_id = _as_str(item.get("operationId")) or f"{method}_{path_template}"
            operations.append(
                AdminOperation(
                    operation_id=operation_id,
                    method=method.upper(),
                    path_template=path_template,
                    summary=_as_str(item.get("summary")) or operation_id,
                    description=_as_str(item.get("description")) or "",
                    tags=_as_str_tuple(item.get("tags")),
                    capability=_as_str(item.get("x-request-engine-capability")),
                    kind=_as_str(item.get("x-request-engine-kind")),
                    idempotency=_as_str(item.get("x-request-engine-idempotency")),
                    exposure=_as_str(item.get("x-request-engine-exposure")),
                    owner=_as_str(item.get("x-request-engine-owner")),
                    tool_name=_as_str(item.get("x-request-engine-tool-name")),
                    tool_audiences=_as_str_tuple(item.get("x-request-engine-tool-audiences")),
                    auth_kind=_auth_kind(path_template, method),
                    console_flow=_console_flow(path_template),
                    parameters=_extract_parameters(item, resolver),
                    body_schema=_extract_body_schema(item, resolver),
                )
            )
    return AdminCatalog(operations=tuple(sorted(operations, key=lambda op: op.operation_id)))


__all__ = [
    "AdminCatalog",
    "AdminOperation",
    "AdminParameter",
    "load_catalog",
]
