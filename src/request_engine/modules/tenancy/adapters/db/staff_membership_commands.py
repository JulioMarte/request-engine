from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffCommand,
    ReplaceStaffAuthorityCommand,
    TransitionStaffMembershipCommand,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _validate_provenance_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("provenance_reference must contain between 1 and 500 characters")
    return normalized


def _validate_tenant_control_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("desired_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane is not AuthorityPlane.TENANT_CONTROL:
            raise ValueError(f"capability is not tenant-control authority: {capability}")
    return capabilities


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise ValueError("staff membership administration requires a HUMAN actor")


class PostgresStaffMembershipCommands:
    """Typed application boundary over RE-owned Staff lifecycle functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def invite_native_staff(
        self,
        actor: ActorContext,
        command: InviteNativeStaffCommand,
    ) -> UUID:
        _require_human_actor(actor)
        provenance = _validate_provenance_reference(command.provenance_reference)
        async with actor_transaction(self._session_factory, actor) as session:
            result = await session.execute(
                text(
                    """
                    SELECT request_engine.invite_native_staff(
                        :membership_id,
                        :principal_id,
                        :binding_id,
                        :identity_authority_id,
                        :native_identity_id,
                        :authority_anchor_party_id,
                        :provenance_reference
                    )
                    """
                ),
                {
                    "membership_id": command.membership_id,
                    "principal_id": command.principal_id,
                    "binding_id": command.binding_id,
                    "identity_authority_id": command.identity_authority_id,
                    "native_identity_id": command.native_identity_id,
                    "authority_anchor_party_id": command.authority_anchor_party_id,
                    "provenance_reference": provenance,
                },
            )
            binding_id = result.scalar_one()
            if not isinstance(binding_id, UUID):
                raise RuntimeError("staff invitation returned an invalid binding identifier")
            return binding_id

    async def replace_staff_authority(
        self,
        actor: ActorContext,
        command: ReplaceStaffAuthorityCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = _validate_tenant_control_capabilities(command.desired_capabilities)
        provenance = _validate_provenance_reference(command.provenance_reference)
        async with actor_transaction(self._session_factory, actor) as session:
            result = await session.execute(
                text(
                    """
                    SELECT request_engine.replace_staff_authority(
                        :membership_id,
                        :expected_authority_revision,
                        :desired_capabilities,
                        :provenance_reference
                    )
                    """
                ),
                {
                    "membership_id": command.membership_id,
                    "expected_authority_revision": command.expected_authority_revision,
                    "desired_capabilities": list(desired),
                    "provenance_reference": provenance,
                },
            )
            return int(result.scalar_one())

    async def transition_staff_membership(
        self,
        actor: ActorContext,
        command: TransitionStaffMembershipCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        async with actor_transaction(self._session_factory, actor) as session:
            result = await session.execute(
                text(
                    """
                    SELECT request_engine.transition_staff_membership(
                        :membership_id,
                        :expected_revision,
                        :target_status,
                        :provenance_reference
                    )
                    """
                ),
                {
                    "membership_id": command.membership_id,
                    "expected_revision": command.expected_revision,
                    "target_status": command.target_status.value,
                    "provenance_reference": provenance,
                },
            )
            return int(result.scalar_one())
