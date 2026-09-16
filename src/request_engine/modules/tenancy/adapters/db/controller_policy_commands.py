from typing import NoReturn, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.identity_audit import append_identity_audit
from request_engine.modules.tenancy.application.commands.controller_policy_upgrade import (
    CONTROLLER_POLICY_UPGRADE_CAPABILITY,
    UpgradeControllerPolicyCommand,
)
from request_engine.modules.tenancy.application.commands.identity_audit import (
    IdentityAuditAction,
    IdentityAuditDetails,
    IdentityAuditReason,
    IdentitySubjectKind,
)
from request_engine.modules.tenancy.application.errors import (
    ControllerPolicyUpgradeConflict,
    ControllerPolicyUpgradeForbidden,
    ControllerPolicyUpgradeInputInvalid,
    ControllerPolicyUpgradeNotFound,
    ControllerPolicyUpgradeRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

_MAX_POLICY_KEY = 200


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _validate_policy_key(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_POLICY_KEY:
        raise ValueError(f"{name} must contain between 1 and 200 characters")
    return normalized


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise ControllerPolicyUpgradeForbidden("controller policy upgrade requires a HUMAN actor")


def _raise_controller_policy_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise ControllerPolicyUpgradeForbidden(
            "controller policy upgrade authority was denied"
        ) from exc
    if sqlstate == "P0002":
        raise ControllerPolicyUpgradeNotFound(
            "target Principal is not visible in this tenant"
        ) from exc
    if sqlstate in {"40001", "40P01"}:
        raise ControllerPolicyUpgradeRevisionConflict(
            "controller policy revision is stale"
        ) from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise ControllerPolicyUpgradeConflict(
            "controller policy upgrade conflicts with current authority state"
        ) from exc
    if sqlstate == "22023":
        raise ControllerPolicyUpgradeInputInvalid(
            "controller policy upgrade input was rejected"
        ) from exc
    raise exc


def _replay_revision(replay: dict[str, object]) -> int:
    value = replay.get("authority_revision")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(
            "completed controller policy upgrade replay has invalid authority_revision"
        )
    return value


class PostgresControllerPolicyCommands:
    """Typed, idempotent application boundary over the controller-policy upgrade."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def upgrade_controller_policy(
        self,
        actor: ActorContext,
        command: UpgradeControllerPolicyCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        source_policy_key = _validate_policy_key(command.source_policy_key, "source_policy_key")
        target_policy_key = _validate_policy_key(command.target_policy_key, "target_policy_key")
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        provenance_reference = f"policy:{target_policy_key};source:{source_policy_key}"
        fingerprint = command_fingerprint(
            CONTROLLER_POLICY_UPGRADE_CAPABILITY,
            {
                "target_principal_id": command.target_principal_id,
                "source_policy_key": source_policy_key,
                "target_policy_key": target_policy_key,
                "expected_authority_revision": command.expected_authority_revision,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=CONTROLLER_POLICY_UPGRADE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay)
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.upgrade_controller_policy(
                            :target_principal_id,
                            :source_policy_key,
                            :target_policy_key,
                            :expected_authority_revision,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "target_principal_id": command.target_principal_id,
                        "source_policy_key": source_policy_key,
                        "target_policy_key": target_policy_key,
                        "expected_authority_revision": command.expected_authority_revision,
                        "provenance_reference": provenance_reference,
                    },
                )
            except DBAPIError as exc:
                _raise_controller_policy_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority_revision": authority_revision},
            )
            await append_identity_audit(
                session,
                actor=actor,
                command_name=CONTROLLER_POLICY_UPGRADE_CAPABILITY,
                aggregate_id=command.target_principal_id,
                idempotency_id=idempotency_id,
                details=IdentityAuditDetails(
                    action=IdentityAuditAction.POLICY_UPGRADE,
                    reason_code=IdentityAuditReason.CONTROLLER_POLICY_UPGRADED,
                    subject_kind=IdentitySubjectKind.TENANT_CONTROLLER,
                    revision_before=command.expected_authority_revision,
                    revision_after=authority_revision,
                    source_policy_key=source_policy_key,
                    target_policy_key=target_policy_key,
                ),
            )
            return authority_revision
