import hashlib
from datetime import UTC, datetime
from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionConflict,
    ControllerPolicyAdoptionDetail,
    ControllerPolicyAdoptionForbidden,
    ControllerPolicyAdoptionInvalid,
    ControllerPolicyAdoptionNotFound,
    ControllerPolicyAdoptionRequestResult,
    ControllerPolicyAdoptionResult,
    ControllerPolicyAdoptionReview,
    ControllerPolicyAdoptionSummary,
    ListControllerPolicyAdoptions,
    RequestControllerPolicyAdoption,
    WithdrawControllerPolicyAdoption,
)
from request_engine.platform.db.session import (
    SessionFactory,
    actor_transaction,
    platform_actor_transaction,
)
from request_engine.platform.idempotency.postgres import command_fingerprint
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.freshness import (
    require_phishing_resistant_authentication,
)
from request_engine.platform.security.platform_context import PlatformActorContext

_ROOT_ADMISSION_CAPABILITY = "organization.bootstrap"
_PLATFORM_APPLY_CAPABILITY = "platform.organization.adopt_initial_controller_policy"


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _map_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise ControllerPolicyAdoptionForbidden() from exc
    if sqlstate == "P0002":
        raise ControllerPolicyAdoptionNotFound() from exc
    if sqlstate in {"40001", "40P01", "23505", "23514", "55000"}:
        raise ControllerPolicyAdoptionConflict() from exc
    if sqlstate == "22023":
        raise ControllerPolicyAdoptionInvalid() from exc
    raise exc


def _require_tenant_root_context(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise ControllerPolicyAdoptionForbidden()
    if actor.identity_binding_id is None:
        raise ControllerPolicyAdoptionForbidden()
    require_phishing_resistant_authentication(actor, now=datetime.now(UTC))


def _require_platform_context(actor: PlatformActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
        _PLATFORM_APPLY_CAPABILITY
    ):
        raise ControllerPolicyAdoptionForbidden()
    require_phishing_resistant_authentication(actor, now=datetime.now(UTC))


def _digests(key: str, capability: str, values: dict[str, object]) -> tuple[str, str]:
    normalized_key = key.strip()
    if not normalized_key:
        raise ValueError("Idempotency-Key is required")
    return (
        hashlib.sha256(normalized_key.encode("utf-8")).hexdigest(),
        command_fingerprint(capability, values),
    )


class PostgresControllerPolicyAdoptionCommands:
    """Persist root consent and apply only that immutable consent from platform control."""

    def __init__(
        self,
        tenant_session_factory: SessionFactory,
        platform_session_factory: SessionFactory | None = None,
    ):
        self._tenant_sessions = tenant_session_factory
        self._platform_sessions = platform_session_factory

    async def request_adoption(
        self, actor: ActorContext, command: RequestControllerPolicyAdoption
    ) -> ControllerPolicyAdoptionRequestResult:
        _require_tenant_root_context(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        reason = command.reason.strip()
        if not 1 <= len(reason) <= 500:
            raise ValueError("reason must contain between 1 and 500 characters")
        key_digest, intent_digest = _digests(
            command.idempotency_key,
            "controller_policy_adoption_request_create",
            {"expected_authority_revision": command.expected_authority_revision, "reason": reason},
        )
        async with actor_transaction(self._tenant_sessions, actor) as session:
            try:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_cmd.request_controller_policy_adoption(
                          :binding_id,:expected_revision,:reason,:key_digest,:intent_digest,
                          :correlation_id)
                        """),
                        {
                            "binding_id": actor.identity_binding_id,
                            "expected_revision": command.expected_authority_revision,
                            "reason": reason,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                            "correlation_id": actor.correlation_id,
                        },
                    )
                ).one()
            except DBAPIError as exc:
                _map_db_error(exc)
        return ControllerPolicyAdoptionRequestResult(
            request_id=UUID(str(row.request_id)),
            source_policy_key=str(row.source_policy_key),
            target_policy_key=str(row.target_policy_key),
            authority_revision=int(row.authority_revision),
            request_revision=int(row.request_revision),
            status=str(row.status),
            expires_at=row.expires_at.isoformat(),
        )

    async def withdraw_adoption(
        self, actor: ActorContext, command: WithdrawControllerPolicyAdoption
    ) -> tuple[int, str]:
        _require_tenant_root_context(actor)
        if command.expected_request_revision <= 0:
            raise ValueError("expected_request_revision must be positive")
        key_digest, intent_digest = _digests(
            command.idempotency_key,
            "controller_policy_adoption_request_withdraw",
            {
                "request_id": command.request_id,
                "expected_request_revision": command.expected_request_revision,
            },
        )
        async with actor_transaction(self._tenant_sessions, actor) as session:
            try:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_cmd.withdraw_controller_policy_adoption(
                          :request_id,:expected_revision,:binding_id,:key_digest,:intent_digest)
                        """),
                        {
                            "request_id": command.request_id,
                            "expected_revision": command.expected_request_revision,
                            "binding_id": actor.identity_binding_id,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
            except DBAPIError as exc:
                _map_db_error(exc)
        return int(row.request_revision), str(row.status)

    async def apply_adoption(
        self, actor: PlatformActorContext, command: ApplyControllerPolicyAdoption
    ) -> ControllerPolicyAdoptionResult:
        _require_platform_context(actor)
        if self._platform_sessions is None:
            raise RuntimeError("Platform policy-adoption connection was not composed")
        if command.expected_request_revision <= 0:
            raise ValueError("expected_request_revision must be positive")
        key_digest, intent_digest = _digests(
            command.idempotency_key,
            _PLATFORM_APPLY_CAPABILITY,
            {
                "request_id": command.request_id,
                "expected_request_revision": command.expected_request_revision,
            },
        )
        async with platform_actor_transaction(self._platform_sessions, actor) as session:
            try:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.apply_controller_policy_adoption(
                          :request_id,:expected_revision,:key_digest,:intent_digest)
                        """),
                        {
                            "request_id": command.request_id,
                            "expected_revision": command.expected_request_revision,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
            except DBAPIError as exc:
                _map_db_error(exc)
        return ControllerPolicyAdoptionResult(
            fact_id=UUID(str(row.fact_id)),
            request_id=UUID(str(row.request_id)),
            organization_id=UUID(str(row.organization_id)),
            controller_principal_id=UUID(str(row.controller_principal_id)),
            platform_approver_principal_id=UUID(str(row.platform_approver_principal_id)),
            source_policy_key=str(row.source_policy_key),
            target_policy_key=str(row.target_policy_key),
            authority_revision_before=int(row.authority_revision_before),
            authority_revision_after=int(row.authority_revision_after),
            added_capabilities=tuple(row.added_capabilities),
            request_revision=int(row.request_revision),
        )

    async def list_adoptions(
        self,
        actor: PlatformActorContext,
        query: ListControllerPolicyAdoptions,
    ) -> tuple[ControllerPolicyAdoptionSummary, ...]:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            "platform.organization.read"
        ):
            raise ControllerPolicyAdoptionForbidden()
        async with platform_actor_transaction(self._tenant_sessions, actor) as session:
            try:
                result = await session.execute(
                    text("""
                    SELECT * FROM request_platform.list_controller_policy_adoptions(
                      CAST(:after AS uuid), CAST(:limit AS integer), CAST(:request_id AS uuid))
                    """),
                    {"after": query.after, "limit": query.limit, "request_id": query.request_id},
                )
            except DBAPIError as exc:
                _map_db_error(exc)
        return tuple(
            ControllerPolicyAdoptionSummary(
                request_id=UUID(str(row.request_id)),
                organization_id=UUID(str(row.organization_id)),
                controller_principal_id=UUID(str(row.controller_principal_id)),
                source_policy_key=str(row.source_policy_key),
                target_policy_key=str(row.target_policy_key),
                expected_authority_revision=int(row.expected_authority_revision),
                status=str(row.status),
                request_revision=int(row.revision),
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
            for row in result
        )

    async def get_review(
        self, actor: PlatformActorContext, request_id: UUID
    ) -> ControllerPolicyAdoptionReview:
        _require_platform_context(actor)
        if self._platform_sessions is None:
            raise RuntimeError("Platform adoption review requires the private control connection")
        async with platform_actor_transaction(self._platform_sessions, actor) as session:
            try:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_platform.review_controller_policy_adoption("
                            ":request_id)"
                        ),
                        {"request_id": request_id},
                    )
                ).one()
            except DBAPIError as exc:
                _map_db_error(exc)
        summary = ControllerPolicyAdoptionSummary(
            request_id=UUID(str(row.request_id)),
            organization_id=UUID(str(row.organization_id)),
            controller_principal_id=UUID(str(row.controller_principal_id)),
            source_policy_key=str(row.source_policy_key),
            target_policy_key=str(row.target_policy_key),
            expected_authority_revision=int(row.expected_authority_revision),
            status="pending",
            request_revision=int(row.request_revision),
            created_at=row.created_at,
            expires_at=row.expires_at,
        )
        return ControllerPolicyAdoptionReview(
            request=summary,
            reason=str(row.reason),
            current_authority_revision=int(row.current_authority_revision),
            proposed_capabilities=tuple(row.proposed_capabilities or ()),
            revoked_capabilities=tuple(row.revoked_capabilities or ()),
        )

    async def get_adoption(
        self, actor: ActorContext, request_id: UUID
    ) -> ControllerPolicyAdoptionDetail:
        _require_tenant_root_context(actor)
        async with actor_transaction(self._tenant_sessions, actor) as session:
            try:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_cmd.read_controller_policy_adoption(
                          :request_id,:binding_id)
                        """),
                        {"request_id": request_id, "binding_id": actor.identity_binding_id},
                    )
                ).one()
            except DBAPIError as exc:
                _map_db_error(exc)
        return ControllerPolicyAdoptionDetail(
            request_id=UUID(str(row.request_id)),
            organization_id=UUID(str(row.organization_id)),
            controller_principal_id=UUID(str(row.controller_principal_id)),
            source_policy_key=str(row.source_policy_key),
            target_policy_key=str(row.target_policy_key),
            expected_authority_revision=int(row.expected_authority_revision),
            status=str(row.status),
            request_revision=int(row.revision),
            created_at=row.created_at,
            expires_at=row.expires_at,
            authority_revision_before=(
                None
                if row.authority_revision_before is None
                else int(row.authority_revision_before)
            ),
            authority_revision_after=(
                None if row.authority_revision_after is None else int(row.authority_revision_after)
            ),
            added_capabilities=tuple(row.added_capabilities or ()),
        )
