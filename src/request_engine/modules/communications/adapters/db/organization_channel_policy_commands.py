import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as policy_commands,
)
from request_engine.modules.communications.application.errors import (
    OrganizationChannelPolicyRevisionConflict,
)
from request_engine.modules.communications.domain.delivery_policy import parse_delivery_policy
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_operational_authority,
)

_CAPABILITY = "communications.set_channel_policy"


class PostgresOrganizationChannelPolicyCommands:
    """Configure the organization-level channel policy for one purpose."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_organization_channel_policy(
        self, command: policy_commands.SetOrganizationChannelPolicyCommand
    ) -> policy_commands.OrganizationChannelPolicyState:
        channel_policy = _policy_json(command)
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "purpose": command.policy.purpose,
                "enabled": command.policy.enabled,
                "channel_policy": channel_policy,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["state"]))

            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            state = await _upsert_policy(
                session,
                organization_id=command.organization_id,
                purpose=command.policy.purpose,
                enabled=command.policy.enabled,
                channel_policy=channel_policy,
                expected_revision=command.expected_revision,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="OrganizationChannelPolicy",
                aggregate_id=command.organization_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "purpose": state.purpose,
                    "enabled": state.enabled,
                    "revision": state.revision,
                },
            )
            await complete_idempotency(session, idempotency_id, {"state": _state_to_json(state)})
            return state


async def _upsert_policy(
    session: AsyncSession,
    *,
    organization_id: UUID,
    purpose: str,
    enabled: bool,
    channel_policy: dict[str, object],
    expected_revision: int,
) -> policy_commands.OrganizationChannelPolicyState:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT revision
                    FROM request_engine.organization_channel_policies
                    WHERE organization_id = :organization_id
                      AND purpose = :purpose
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "purpose": purpose},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        if expected_revision != 0:
            raise OrganizationChannelPolicyRevisionConflict(purpose, expected_revision, 0)
        updated = (
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.organization_channel_policies (
                            organization_id, purpose, enabled, channel_policy, revision
                        ) VALUES (
                            :organization_id, :purpose, :enabled,
                            CAST(:channel_policy AS jsonb), 1
                        )
                        RETURNING revision
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "purpose": purpose,
                        "enabled": enabled,
                        "channel_policy": _json(channel_policy),
                    },
                )
            )
            .mappings()
            .one()
        )
    else:
        current_revision = cast(int, row["revision"])
        if expected_revision != current_revision:
            raise OrganizationChannelPolicyRevisionConflict(
                purpose, expected_revision, current_revision
            )
        updated = (
            (
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.organization_channel_policies
                        SET enabled = :enabled,
                            channel_policy = CAST(:channel_policy AS jsonb),
                            revision = revision + 1,
                            updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id AND purpose = :purpose
                        RETURNING revision
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "purpose": purpose,
                        "enabled": enabled,
                        "channel_policy": _json(channel_policy),
                    },
                )
            )
            .mappings()
            .one()
        )
    return policy_commands.OrganizationChannelPolicyState(
        purpose=purpose,
        enabled=enabled,
        channel_policy=channel_policy,
        revision=cast(int, updated["revision"]),
    )


def _policy_json(command: policy_commands.SetOrganizationChannelPolicyCommand) -> dict[str, object]:
    parse_delivery_policy(
        {
            "channels": list(command.policy.channels),
            "provider_key": command.policy.provider_key,
            "reconcile_after_seconds": command.policy.reconcile_after_seconds,
            "retry_after_seconds": command.policy.retry_after_seconds,
        }
    )
    policy: dict[str, object] = {
        "channels": list(command.policy.channels),
        "reconcile_after_seconds": command.policy.reconcile_after_seconds,
        "retry_after_seconds": command.policy.retry_after_seconds,
    }
    if command.policy.provider_key is not None:
        policy["provider_key"] = command.policy.provider_key
    return policy


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _state_to_json(state: policy_commands.OrganizationChannelPolicyState) -> dict[str, object]:
    return {
        "purpose": state.purpose,
        "enabled": state.enabled,
        "channel_policy": state.channel_policy,
        "revision": state.revision,
    }


def _state_from_json(value: dict[str, object]) -> policy_commands.OrganizationChannelPolicyState:
    return policy_commands.OrganizationChannelPolicyState(
        purpose=cast(str, value["purpose"]),
        enabled=cast(bool, value["enabled"]),
        channel_policy=cast(dict[str, object], value["channel_policy"]),
        revision=cast(int, value["revision"]),
    )
