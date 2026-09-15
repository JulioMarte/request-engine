import hashlib
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.platform_provisioner_lifecycle import (
    PlatformProvisionerLifecycleAction,
    PlatformProvisionerLifecycleConflict,
    PlatformProvisionerLifecycleError,
    PlatformProvisionerLifecycleForbidden,
    PlatformProvisionerLifecycleInvalid,
    PlatformProvisionerLifecycleResult,
    PlatformProvisionerLifecycleRevisionConflict,
    TransitionPlatformProvisionerCommand,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_CAPABILITY = "platform.provisioner.manage_lifecycle"
_DATABASE_ERRORS: dict[str, type[PlatformProvisionerLifecycleError]] = {
    "23505": PlatformProvisionerLifecycleConflict,
    "23514": PlatformProvisionerLifecycleInvalid,
    "22023": PlatformProvisionerLifecycleInvalid,
    "40001": PlatformProvisionerLifecycleRevisionConflict,
    "40P01": PlatformProvisionerLifecycleRevisionConflict,
    "42501": PlatformProvisionerLifecycleForbidden,
    "28000": PlatformProvisionerLifecycleForbidden,
    "55000": PlatformProvisionerLifecycleConflict,
}


class PostgresNativePlatformProvisionerLifecycleCommands:
    """One revisioned platform transaction; PostgreSQL owns replay comparison."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def transition_provisioner(
        self,
        actor: PlatformActorContext,
        command: TransitionPlatformProvisionerCommand,
    ) -> PlatformProvisionerLifecycleResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(_CAPABILITY):
            raise PlatformProvisionerLifecycleForbidden(_CAPABILITY)
        intent = {
            "principal_id": str(command.principal_id),
            "action": command.action.value,
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
                        SELECT * FROM request_platform.transition_native_platform_provisioner(
                            CAST(:principal_id AS uuid),
                            CAST(:action AS text),
                            CAST(:expected_revision AS bigint),
                            CAST(:reason_code AS text),
                            CAST(:case_reference AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "principal_id": command.principal_id,
                            "action": command.action.value,
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
        return PlatformProvisionerLifecycleResult(
            fact_id=UUID(str(row[0])),
            principal_id=UUID(str(row[1])),
            action=PlatformProvisionerLifecycleAction(str(row[2])),
            authority_revision=int(row[3]),
            binding_id=None if row[4] is None else UUID(str(row[4])),
            binding_status=None if row[5] is None else str(row[5]),
        )
