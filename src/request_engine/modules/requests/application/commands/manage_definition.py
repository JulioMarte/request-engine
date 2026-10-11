import json
import re
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from request_engine.modules.requests.application.errors import RequestPayloadInvalid
from request_engine.modules.requests.domain.errors import UnsupportedRequestSchema
from request_engine.modules.requests.domain.schema_validation import validate_request_schema
from request_engine.platform.security.operational_authority import MANAGE_OPERATIONAL_PROFILE_SCOPE

DEFINITION_AUTHORITY_SCOPE = MANAGE_OPERATIONAL_PROFILE_SCOPE


def validate_definition_key(request_key: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", request_key) is None:
        raise RequestPayloadInvalid(
            "$.request_key", "key must be URL-safe ASCII alphanumeric, dot, underscore or hyphen"
        )


@dataclass(frozen=True, slots=True)
class CreateRequestDefinitionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    request_key: str
    display_name: str
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class PublishRequestDefinitionVersionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    definition_id: UUID
    expected_revision: int
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SetRequestDefinitionActiveCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    definition_id: UUID
    expected_revision: int
    active: bool
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RequestDefinitionState:
    definition_id: UUID
    request_key: str
    display_name: str
    active: bool
    revision: int
    version_id: UUID
    version: int
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None


class RequestDefinitionCommands(Protocol):
    async def create_definition(
        self, command: CreateRequestDefinitionCommand
    ) -> RequestDefinitionState: ...
    async def publish_version(
        self, command: PublishRequestDefinitionVersionCommand
    ) -> RequestDefinitionState: ...
    async def set_active(
        self, command: SetRequestDefinitionActiveCommand
    ) -> RequestDefinitionState: ...


def validate_definition_schemas(
    input_schema: dict[str, object],
    result_schema: dict[str, object] | None,
) -> None:
    pending: list[tuple[object, int]] = [(input_schema, 0), (result_schema, 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 4096:
            raise RequestPayloadInvalid("$", "schema nesting or node count exceeds safety limit")
        if isinstance(value, dict):
            pending.extend(
                (child, depth + 1) for child in cast(dict[object, object], value).values()
            )
        elif isinstance(value, (list, tuple)):
            pending.extend(
                (child, depth + 1) for child in cast(list[object] | tuple[object, ...], value)
            )
    try:
        encoded = json.dumps((input_schema, result_schema), allow_nan=False)
    except (TypeError, ValueError):
        raise RequestPayloadInvalid("$", "schemas must contain finite JSON values") from None
    if len(encoded.encode("utf-8")) > 65536:
        raise RequestPayloadInvalid("$", "combined schemas exceed 65536 bytes")
    try:
        validate_request_schema(input_schema)
        if result_schema is not None:
            validate_request_schema(result_schema)
    except UnsupportedRequestSchema as exc:
        raise RequestPayloadInvalid(
            exc.path, f"unsupported schema keyword: {exc.keyword}"
        ) from None
