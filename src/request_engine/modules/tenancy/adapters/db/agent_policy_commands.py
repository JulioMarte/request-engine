from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.agent_policy import (
    ReplaceAgentPolicyCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentPolicyForbidden,
    AgentPolicyInputInvalid,
    AgentPolicyNotFound,
)
from request_engine.modules.tenancy.domain.agent_policy import (
    AgentPolicy,
    build_agent_policy,
    validate_agent_policy_rule_set,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.operation_risk import OperationRiskClass

_POLICY_READ_CAPABILITY = "agent.policy.read"
_POLICY_MANAGE_CAPABILITY = "agent.manage_policy"


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _validate_provenance_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("provenance_reference must contain between 1 and 500 characters")
    return normalized


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise AgentPolicyForbidden("agent policy operations require a HUMAN actor")


def _raise_agent_policy_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "22023":
        raise AgentPolicyInputInvalid("agent policy input was rejected") from exc
    if sqlstate == "P0002":
        raise AgentPolicyNotFound("agent profile is not visible in this tenant") from exc
    if sqlstate == "55000":
        raise AgentPolicyForbidden("agent policy change was denied") from exc
    raise exc


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed agent policy idempotency replay has invalid {key}")
    return value


class PostgresAgentPolicyCommands:
    """Typed, idempotent application boundary over RE-owned Agent policy functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_policy(
        self,
        actor: ActorContext,
        agent_principal_id: UUID,
    ) -> AgentPolicy:
        _require_human_actor(actor)
        async with actor_transaction(self._session_factory, actor) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT allowed_capabilities, denied_capabilities, risk_ceiling,
                                   max_mutations_per_minute, policy_revision, provenance_reference
                              FROM request_engine.agent_policies
                             WHERE organization_id = :organization_id
                               AND agent_principal_id = :agent_principal_id
                            """
                        ),
                        {
                            "organization_id": actor.organization_id,
                            "agent_principal_id": agent_principal_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise AgentPolicyNotFound(
                f"Agent policy for {agent_principal_id} was not found in the current tenant"
            )
        return build_agent_policy(
            agent_principal_id=agent_principal_id,
            allowed_capabilities=tuple(row["allowed_capabilities"]),
            denied_capabilities=tuple(row["denied_capabilities"]),
            risk_ceiling=OperationRiskClass(str(row["risk_ceiling"])),
            max_mutations_per_minute=int(row["max_mutations_per_minute"]),
            policy_revision=int(row["policy_revision"]),
            provenance_reference=str(row["provenance_reference"]),
        )

    async def replace_policy(
        self,
        actor: ActorContext,
        command: ReplaceAgentPolicyCommand,
    ) -> int:
        _require_human_actor(actor)
        allowed, denied, risk_ceiling = validate_agent_policy_rule_set(
            risk_ceiling=command.risk_ceiling,
            max_mutations_per_minute=command.max_mutations_per_minute,
            allowed_capabilities=command.allowed_capabilities,
            denied_capabilities=command.denied_capabilities,
        )
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _POLICY_MANAGE_CAPABILITY,
            {
                "agent_principal_id": command.agent_principal_id,
                "allowed_capabilities": allowed,
                "denied_capabilities": denied,
                "risk_ceiling": risk_ceiling.value,
                "max_mutations_per_minute": command.max_mutations_per_minute,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_POLICY_MANAGE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "policy_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.upsert_agent_policy(
                            :agent_principal_id,
                            :allowed_capabilities,
                            :denied_capabilities,
                            :risk_ceiling,
                            :max_mutations_per_minute,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "agent_principal_id": command.agent_principal_id,
                        "allowed_capabilities": list(allowed),
                        "denied_capabilities": list(denied),
                        "risk_ceiling": risk_ceiling.value,
                        "max_mutations_per_minute": command.max_mutations_per_minute,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_agent_policy_db_error(exc)
            policy_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"policy_revision": policy_revision},
            )
            return policy_revision
