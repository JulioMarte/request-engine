from __future__ import annotations

import hashlib
import json
from typing import Any, Never
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    ActivateConfiguration,
    ConfigurationMutationResult,
    ConfigurationRevision,
    DisableConfiguration,
    PlatformConfigurationConflict,
    PlatformConfigurationError,
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
    PlatformConfigurationRevisionConflict,
    SecretBindingMetadata,
    StageConfiguration,
    ValidateConfiguration,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_DATABASE_ERRORS: dict[str, type[PlatformConfigurationError]] = {
    "23505": PlatformConfigurationConflict,
    "23514": PlatformConfigurationInvalid,
    "22023": PlatformConfigurationInvalid,
    "40001": PlatformConfigurationRevisionConflict,
    "40P01": PlatformConfigurationRevisionConflict,
    "42501": PlatformConfigurationForbidden,
    "28000": PlatformConfigurationForbidden,
    "P0002": PlatformConfigurationNotFound,
}


class PostgresPlatformConfigurationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_revisions(
        self,
        actor: PlatformActorContext,
        configuration_kind: str | None = None,
    ) -> list[ConfigurationRevision]:
        _require(actor, "platform.configuration.read")
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT * FROM "
                            "request_platform.read_platform_configuration_revisions("
                            "CAST(:kind AS text))"
                        ),
                        {"kind": configuration_kind},
                    )
                ).all()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return [_revision(row) for row in rows]

    async def get_revision(
        self,
        actor: PlatformActorContext,
        configuration_kind: str,
        revision: int,
    ) -> ConfigurationRevision:
        rows = await self.list_revisions(actor, configuration_kind)
        for row in rows:
            if row.revision == revision:
                return row
        raise PlatformConfigurationNotFound()

    async def get_secret_binding(
        self,
        actor: PlatformActorContext,
        binding_id: UUID,
    ) -> SecretBindingMetadata:
        _require(actor, "platform.configuration.read")
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM "
                            "request_platform.read_platform_secret_binding("
                            "CAST(:binding_id AS uuid))"
                        ),
                        {"binding_id": binding_id},
                    )
                ).one_or_none()
        except DBAPIError as exc:
            _raise_mapped(exc)
        if row is None:
            raise PlatformConfigurationNotFound()
        return SecretBindingMetadata(
            binding_id=UUID(str(row[0])),
            purpose=str(row[1]),
            backend=str(row[2]),
            backend_version=int(row[3]),
            status=str(row[4]),
            revision=int(row[5]),
            created_at=row[6],
            rotated_at=row[7],
            revoked_at=row[8],
        )


class PostgresPlatformConfigurationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def stage(
        self,
        actor: PlatformActorContext,
        command: StageConfiguration,
    ) -> ConfigurationMutationResult:
        return await self._execute(
            actor,
            "platform.configuration.stage",
            """
            SELECT * FROM request_platform.stage_platform_configuration(
                CAST(:kind AS text),
                CAST(:provider AS text),
                CAST(:configuration AS jsonb),
                CAST(:secret_binding_id AS uuid),
                CAST(:key_digest AS text),
                CAST(:intent_digest AS text)
            )
            """,
            {
                "kind": command.configuration_kind,
                "provider": command.provider_kind,
                "configuration": json.dumps(command.configuration),
                "secret_binding_id": command.secret_binding_id,
                "key_digest": _digest_text(command.idempotency_key),
                "intent_digest": _digest_json(
                    {
                        "configuration_kind": command.configuration_kind,
                        "provider_kind": command.provider_kind,
                        "configuration": command.configuration,
                        "secret_binding_id": (
                            None
                            if command.secret_binding_id is None
                            else str(command.secret_binding_id)
                        ),
                    }
                ),
            },
        )

    async def validate(
        self,
        actor: PlatformActorContext,
        command: ValidateConfiguration,
    ) -> ConfigurationMutationResult:
        return await self._execute(
            actor,
            "platform.configuration.validate",
            """
            SELECT * FROM request_platform.validate_platform_configuration(
                CAST(:kind AS text),
                CAST(:revision AS bigint),
                CAST(:key_digest AS text),
                CAST(:intent_digest AS text)
            )
            """,
            {
                "kind": command.configuration_kind,
                "revision": command.revision,
                "key_digest": _digest_text(command.idempotency_key),
                "intent_digest": _digest_json(
                    {
                        "configuration_kind": command.configuration_kind,
                        "revision": command.revision,
                    }
                ),
            },
        )

    async def activate(
        self,
        actor: PlatformActorContext,
        command: ActivateConfiguration,
    ) -> ConfigurationMutationResult:
        return await self._execute(
            actor,
            "platform.configuration.activate",
            """
            SELECT * FROM request_platform.activate_platform_configuration(
                CAST(:kind AS text),
                CAST(:revision AS bigint),
                CAST(:expected_active_revision AS bigint),
                CAST(:key_digest AS text),
                CAST(:intent_digest AS text)
            )
            """,
            {
                "kind": command.configuration_kind,
                "revision": command.revision,
                "expected_active_revision": command.expected_active_revision,
                "key_digest": _digest_text(command.idempotency_key),
                "intent_digest": _digest_json(
                    {
                        "configuration_kind": command.configuration_kind,
                        "revision": command.revision,
                        "expected_active_revision": command.expected_active_revision,
                    }
                ),
            },
        )

    async def disable(
        self,
        actor: PlatformActorContext,
        command: DisableConfiguration,
    ) -> ConfigurationMutationResult:
        return await self._execute(
            actor,
            "platform.configuration.disable",
            """
            SELECT * FROM request_platform.disable_platform_configuration(
                CAST(:kind AS text),
                CAST(:revision AS bigint),
                CAST(:key_digest AS text),
                CAST(:intent_digest AS text)
            )
            """,
            {
                "kind": command.configuration_kind,
                "revision": command.revision,
                "key_digest": _digest_text(command.idempotency_key),
                "intent_digest": _digest_json(
                    {
                        "configuration_kind": command.configuration_kind,
                        "revision": command.revision,
                    }
                ),
            },
        )

    async def _execute(
        self,
        actor: PlatformActorContext,
        capability: str,
        sql: str,
        params: dict[str, object],
    ) -> ConfigurationMutationResult:
        _require(actor, capability)
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (await session.execute(text(sql), params)).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return ConfigurationMutationResult(
            configuration_revision_id=UUID(str(row[0])),
            revision=int(row[1]),
            state=str(row[2]),
        )


def _require(actor: PlatformActorContext, capability: str) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(capability):
        raise PlatformConfigurationForbidden(capability)


def _revision(row: Row[Any]) -> ConfigurationRevision:
    values = row
    return ConfigurationRevision(
        configuration_revision_id=UUID(str(values[0])),
        configuration_kind=str(values[1]),
        provider_kind=str(values[2]),
        revision=int(values[3]),
        configuration=dict(values[4]),
        secret_binding_id=None if values[5] is None else UUID(str(values[5])),
        state=str(values[6]),
        created_by_principal_id=UUID(str(values[7])),
        created_at=values[8],
        validated_at=values[9],
        activated_at=values[10],
        disabled_at=values[11],
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _raise_mapped(exc: DBAPIError) -> Never:
    error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
    if error_type is None:
        raise exc
    raise error_type() from None
