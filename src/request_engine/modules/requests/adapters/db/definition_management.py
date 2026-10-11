import json
from dataclasses import asdict
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.requests.application.commands.manage_definition import (
    DEFINITION_AUTHORITY_SCOPE,
    CreateRequestDefinitionCommand,
    PublishRequestDefinitionVersionCommand,
    RequestDefinitionState,
    SetRequestDefinitionActiveCommand,
    validate_definition_key,
    validate_definition_schemas,
)
from request_engine.modules.requests.application.errors import (
    RequestDefinitionConfigurationConflict,
    RequestDefinitionNotFound,
    RequestPayloadInvalid,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    require_principal_serialized_operational_authority,
)

DefinitionCommand = (
    CreateRequestDefinitionCommand
    | PublishRequestDefinitionVersionCommand
    | SetRequestDefinitionActiveCommand
)

DEFINITION_STATE_SELECT = """
    SELECT d.id, d.request_key, d.display_name, d.active, d.revision,
           v.id AS version_id, v.version, v.input_schema, v.result_schema
    FROM request_engine.request_definitions d
    JOIN LATERAL (
        SELECT id, version, input_schema, result_schema
        FROM request_engine.request_definition_versions
        WHERE organization_id=d.organization_id AND request_definition_id=d.id
          AND (CAST(:version AS integer) IS NULL OR version=CAST(:version AS integer))
        ORDER BY version DESC LIMIT 1
    ) v ON true
"""


async def read_definition_state(
    session: AsyncSession,
    organization_id: UUID,
    definition_id: UUID,
    version: int | None = None,
) -> RequestDefinitionState | None:
    row = (
        (
            await session.execute(
                text(
                    DEFINITION_STATE_SELECT
                    + "WHERE d.organization_id=:organization_id AND d.id=:definition_id"
                ),
                {
                    "organization_id": organization_id,
                    "definition_id": definition_id,
                    "version": version,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return state_from_row(row)


def state_from_row(row: RowMapping) -> RequestDefinitionState:
    return RequestDefinitionState(
        cast(UUID, row["id"]),
        cast(str, row["request_key"]),
        cast(str, row["display_name"]),
        cast(bool, row["active"]),
        cast(int, row["revision"]),
        cast(UUID, row["version_id"]),
        cast(int, row["version"]),
        cast(dict[str, object], row["input_schema"]),
        cast(dict[str, object] | None, row["result_schema"]),
    )


def state_from_receipt(value: dict[str, object]) -> RequestDefinitionState:
    return RequestDefinitionState(
        UUID(cast(str, value["definition_id"])),
        cast(str, value["request_key"]),
        cast(str, value["display_name"]),
        cast(bool, value["active"]),
        cast(int, value["revision"]),
        UUID(cast(str, value["version_id"])),
        cast(int, value["version"]),
        cast(dict[str, object], value["input_schema"]),
        cast(dict[str, object] | None, value["result_schema"]),
    )


class PostgresRequestDefinitionCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_definition(
        self,
        command: CreateRequestDefinitionCommand,
    ) -> RequestDefinitionState:
        if not command.request_key.strip() or not command.display_name.strip():
            raise RequestPayloadInvalid("$", "request_key and display_name must not be blank")
        validate_definition_key(command.request_key)
        return await self._execute(command, "requests.create_definition")

    async def publish_version(
        self,
        command: PublishRequestDefinitionVersionCommand,
    ) -> RequestDefinitionState:
        return await self._execute(command, "requests.publish_definition_version")

    async def set_active(
        self, command: SetRequestDefinitionActiveCommand
    ) -> RequestDefinitionState:
        return await self._execute(command, "requests.set_definition_active")

    async def _execute(self, command: DefinitionCommand, capability: str) -> RequestDefinitionState:
        if not command.idempotency_key:
            raise RequestPayloadInvalid("$", "idempotency key is required")
        if not isinstance(command, SetRequestDefinitionActiveCommand):
            validate_definition_schemas(command.input_schema, command.result_schema)
        values = asdict(command)
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
            )
            authority = await require_principal_serialized_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=DEFINITION_AUTHORITY_SCOPE,
            )
            receipt_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=command_fingerprint(capability, values),
            )
            if replay is not None:
                return state_from_receipt(replay)
            params: dict[str, object] = values.copy()
            if isinstance(command, CreateRequestDefinitionCommand):
                definition_id = cast(
                    UUID,
                    (
                        await session.execute(
                            text("""
                    INSERT INTO request_engine.request_definitions
                        (organization_id,request_key,display_name)
                    VALUES (:organization_id,:request_key,:display_name) RETURNING id
                """),
                            params,
                        )
                    ).scalar_one(),
                )
                params["definition_id"] = definition_id
                version = 1
            else:
                definition_id = command.definition_id
                current_revision = (
                    await session.execute(
                        text("""
                    SELECT revision FROM request_engine.request_definitions
                    WHERE organization_id=:organization_id AND id=:definition_id FOR UPDATE
                """),
                        params,
                    )
                ).scalar_one_or_none()
                if current_revision is None:
                    raise RequestDefinitionNotFound(str(definition_id), None)
                if current_revision != command.expected_revision:
                    raise RequestDefinitionConfigurationConflict(
                        "definition revision changed",
                        cast(int, current_revision),
                    )
                state = await read_definition_state(session, command.organization_id, definition_id)
                if state is None:
                    raise RequestDefinitionNotFound(str(definition_id), None)
                version = state.version + 1
                if isinstance(command, SetRequestDefinitionActiveCommand):
                    await session.execute(
                        text("""
                        UPDATE request_engine.request_definitions
                        SET active=:active,revision=revision+1,updated_at=clock_timestamp()
                        WHERE organization_id=:organization_id AND id=:definition_id
                    """),
                        params,
                    )
                else:
                    await session.execute(
                        text("""
                        UPDATE request_engine.request_definitions
                        SET revision=revision+1,updated_at=clock_timestamp()
                        WHERE organization_id=:organization_id AND id=:definition_id
                    """),
                        params,
                    )
            if not isinstance(command, SetRequestDefinitionActiveCommand):
                params.update(
                    {
                        "version": version,
                        "input_schema": json.dumps(command.input_schema, allow_nan=False),
                        "result_schema": json.dumps(command.result_schema, allow_nan=False)
                        if command.result_schema is not None
                        else None,
                    }
                )
                await session.execute(
                    text("""
                    INSERT INTO request_engine.request_definition_versions
                        (organization_id,request_definition_id,version,input_schema,result_schema)
                    VALUES (:organization_id,:definition_id,:version,
                            CAST(:input_schema AS jsonb),CAST(:result_schema AS jsonb))
                """),
                    params,
                )
            result = await read_definition_state(session, command.organization_id, definition_id)
            if result is None:
                raise RuntimeError("definition command lost its own result")
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="request_definition",
                aggregate_id=definition_id,
                idempotency_id=receipt_id,
                details={
                    "revision": result.revision,
                    "version": result.version,
                    "authority": authority.audit_details(),
                },
            )
            receipt = cast(dict[str, object], json.loads(json.dumps(asdict(result), default=str)))
            await complete_idempotency(session, receipt_id, receipt)
            return result
