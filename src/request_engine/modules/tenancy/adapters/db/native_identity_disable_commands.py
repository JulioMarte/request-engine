import hashlib
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.native_identity_disable import (
    NATIVE_IDENTITY_DISABLE_CAPABILITY,
    DisableNativeIdentityCommand,
    DisableNativeIdentityResult,
    NativeIdentityDisableConflict,
    NativeIdentityDisableError,
    NativeIdentityDisableForbidden,
    NativeIdentityDisableInvalid,
    NativeIdentityDisableNotFound,
    NativeIdentityDisableRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_DATABASE_ERRORS: dict[str, type[NativeIdentityDisableError]] = {
    "23505": NativeIdentityDisableConflict,
    "23514": NativeIdentityDisableInvalid,
    "22023": NativeIdentityDisableInvalid,
    "40001": NativeIdentityDisableRevisionConflict,
    "40P01": NativeIdentityDisableRevisionConflict,
    "42501": NativeIdentityDisableForbidden,
    "28000": NativeIdentityDisableForbidden,
    "55000": NativeIdentityDisableConflict,
    "P0002": NativeIdentityDisableNotFound,
}


class PostgresNativeIdentityDisableCommands:
    """One governed platform transaction; PostgreSQL owns continuity and replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def disable_identity(
        self,
        actor: PlatformActorContext,
        command: DisableNativeIdentityCommand,
    ) -> DisableNativeIdentityResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            NATIVE_IDENTITY_DISABLE_CAPABILITY
        ):
            raise NativeIdentityDisableForbidden(NATIVE_IDENTITY_DISABLE_CAPABILITY)
        intent = {
            "native_identity_id": str(command.native_identity_id),
            "expected_revision": command.expected_revision,
            "reason_code": command.normalized_reason_code,
            "external_case_reference": command.normalized_case_reference,
        }
        intent_digest = hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.disable_native_identity(
                            CAST(:native_identity_id AS uuid),
                            CAST(:expected_revision AS bigint),
                            CAST(:reason_code AS text),
                            CAST(:case_reference AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "native_identity_id": command.native_identity_id,
                            "expected_revision": command.expected_revision,
                            "reason_code": command.normalized_reason_code,
                            "case_reference": command.normalized_case_reference,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
            if error_type is None:
                raise
            raise error_type() from None
        return DisableNativeIdentityResult(
            fact_id=UUID(str(row[0])),
            native_identity_id=UUID(str(row[1])),
            revision_after=int(row[2]),
            affected_tenant_count=int(row[3]),
            affected_platform=bool(row[4]),
        )
