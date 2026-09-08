from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffCommand,
    ReplaceStaffAuthorityCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"staff.manage_authority", "staff.invite"}),
        principal_kind=PrincipalKind.HUMAN,
    )


def _writer() -> PostgresStaffMembershipCommands:
    return PostgresStaffMembershipCommands(cast(SessionFactory, object()))


@pytest.mark.asyncio
async def test_staff_authority_rejects_non_tenant_control_and_noncanonical_keys() -> None:
    writer = _writer()
    actor = _actor()

    for capabilities, match in (
        (("appointments.cancel",), "not tenant-control"),
        (("future.staff.superuser",), "unknown or non-canonical"),
        (("staff.invite", "staff.invite"), "duplicates"),
    ):
        with pytest.raises(ValueError, match=match):
            await writer.replace_staff_authority(
                actor,
                ReplaceStaffAuthorityCommand(
                    membership_id=uuid4(),
                    expected_authority_revision=1,
                    desired_capabilities=capabilities,
                    provenance_reference="staff-authority:test",
                    idempotency_key="authority-test",
                ),
            )


@pytest.mark.asyncio
async def test_staff_invitation_rejects_invalid_provenance_before_db_access() -> None:
    writer = _writer()
    actor = _actor()

    for provenance in ("   ", "x" * 501):
        with pytest.raises(ValueError, match="between 1 and 500"):
            await writer.invite_native_staff(
                actor,
                InviteNativeStaffCommand(
                    membership_id=uuid4(),
                    principal_id=uuid4(),
                    binding_id=uuid4(),
                    identity_authority_id=uuid4(),
                    native_identity_id=uuid4(),
                    provenance_reference=provenance,
                    idempotency_key="invite-test",
                ),
            )
