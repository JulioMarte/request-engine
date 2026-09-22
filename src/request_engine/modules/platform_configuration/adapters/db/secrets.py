from __future__ import annotations

import hashlib
import json
from typing import Any, Never
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
)
from request_engine.modules.platform_configuration.application.secrets import (
    CreatePlatformSecret,
    PlatformSecretConflict,
    PlatformSecretNotFound,
    RevokePlatformSecret,
    RotatePlatformSecret,
    SecretMutationOperation,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresPlatformSecretMutations:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare_create(
        self,
        actor: PlatformActorContext,
        command: CreatePlatformSecret,
    ) -> SecretMutationOperation:
        _require(actor, "platform.secret.write")
        return await self._prepare(
            actor,
            operation_kind="create",
            purpose=command.purpose,
            backend=command.backend,
            binding_id=None,
            expected_revision=None,
            expected_backend_version=None,
            idempotency_key=command.idempotency_key,
            intent={
                "operation_kind": "create",
                "purpose": command.purpose,
                "backend": command.backend,
            },
        )

    async def prepare_rotate(
        self,
        actor: PlatformActorContext,
        command: RotatePlatformSecret,
    ) -> SecretMutationOperation:
        _require(actor, "platform.secret.rotate")
        return await self._prepare(
            actor,
            operation_kind="rotate",
            purpose=None,
            backend=None,
            binding_id=command.binding_id,
            expected_revision=command.expected_revision,
            expected_backend_version=command.expected_backend_version,
            idempotency_key=command.idempotency_key,
            intent={
                "operation_kind": "rotate",
                "binding_id": str(command.binding_id),
                "expected_revision": command.expected_revision,
                "expected_backend_version": command.expected_backend_version,
            },
        )

    async def prepare_revoke(
        self,
        actor: PlatformActorContext,
        command: RevokePlatformSecret,
    ) -> SecretMutationOperation:
        _require(actor, "platform.secret.revoke")
        return await self._prepare(
            actor,
            operation_kind="revoke",
            purpose=None,
            backend=None,
            binding_id=command.binding_id,
            expected_revision=command.expected_revision,
            expected_backend_version=command.expected_backend_version,
            idempotency_key=command.idempotency_key,
            intent={
                "operation_kind": "revoke",
                "binding_id": str(command.binding_id),
                "expected_revision": command.expected_revision,
                "expected_backend_version": command.expected_backend_version,
            },
        )

    async def mark_backend_applied(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
        backend_version: int,
    ) -> SecretMutationOperation:
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT *
                              FROM request_platform.mark_platform_secret_backend_applied(
                                  CAST(:operation_id AS uuid),
                                  CAST(:backend_version AS integer)
                              )
                            """
                        ),
                        {
                            "operation_id": operation_id,
                            "backend_version": backend_version,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _operation(row)

    async def commit(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
    ) -> SecretMutationOperation:
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT *
                              FROM request_platform.commit_platform_secret_mutation(
                                  CAST(:operation_id AS uuid)
                              )
                            """
                        ),
                        {"operation_id": operation_id},
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _operation(row)

    async def _prepare(
        self,
        actor: PlatformActorContext,
        *,
        operation_kind: str,
        purpose: str | None,
        backend: str | None,
        binding_id: UUID | None,
        expected_revision: int | None,
        expected_backend_version: int | None,
        idempotency_key: str,
        intent: object,
    ) -> SecretMutationOperation:
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT *
                              FROM request_platform.prepare_platform_secret_mutation(
                                  CAST(:operation_kind AS text),
                                  CAST(:purpose AS text),
                                  CAST(:backend AS text),
                                  CAST(:binding_id AS uuid),
                                  CAST(:expected_revision AS bigint),
                                  CAST(:expected_backend_version AS integer),
                                  CAST(:idempotency_key_digest AS text),
                                  CAST(:intent_digest AS text)
                              )
                            """
                        ),
                        {
                            "operation_kind": operation_kind,
                            "purpose": purpose,
                            "backend": backend,
                            "binding_id": binding_id,
                            "expected_revision": expected_revision,
                            "expected_backend_version": expected_backend_version,
                            "idempotency_key_digest": _digest_text(idempotency_key),
                            "intent_digest": _digest_json(intent),
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _operation(row)


def _require(actor: PlatformActorContext, capability: str) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(capability):
        raise PlatformConfigurationForbidden(capability)


def _operation(row: Row[Any]) -> SecretMutationOperation:
    return SecretMutationOperation(
        operation_id=UUID(str(row[0])),
        operation_kind=str(row[1]),
        binding_id=None if row[2] is None else UUID(str(row[2])),
        secret_id=UUID(str(row[3])),
        purpose=str(row[4]),
        backend=str(row[5]),
        expected_binding_revision=None if row[6] is None else int(row[6]),
        expected_backend_version=None if row[7] is None else int(row[7]),
        applied_backend_version=None if row[8] is None else int(row[8]),
        state=str(row[9]),
        result_binding_id=None if row[10] is None else UUID(str(row[10])),
        result_binding_revision=None if row[11] is None else int(row[11]),
        result_binding_status=None if row[12] is None else str(row[12]),
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _raise_mapped(exc: DBAPIError) -> Never:
    sqlstate = str(getattr(exc.orig, "sqlstate", ""))
    if sqlstate in {"23505", "40001", "40P01"}:
        raise PlatformSecretConflict() from None
    if sqlstate in {"42501", "28000"}:
        raise PlatformConfigurationForbidden() from None
    if sqlstate in {"22023", "23514", "55000"}:
        raise PlatformConfigurationInvalid() from None
    if sqlstate == "P0002":
        raise PlatformSecretNotFound() from None
    raise exc
