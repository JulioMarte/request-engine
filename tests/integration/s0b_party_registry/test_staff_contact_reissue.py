"""Staff contact re-issuance policy and expiry behavior on real PostgreSQL.

An unexpired, unconsumed code blocks re-issuance: the typed conflict carries
the pending expiry, no new code is generated and the attempt counter stays
untouched. Only an expired (or exhausted) code may be replaced. An expired
code can never confirm the contact: the correct-but-expired code is rejected
without flipping `verified` or consuming an attempt. Setting
`verification_expires_at` to the past via direct SQL is a valid prerequisite:
the re-issuance guard blocks on pending state, not on that column.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.tenancy.application.errors import (
    VerificationAlreadyPending,
    VerificationCodeExpired,
)
from request_engine.platform.db.session import SessionFactory

from ._party_support import PgConnection, outbox_rows
from ._party_world import PartyRegistryWorld
from ._staff_support import (
    EVENT_TYPE,
    confirm_command,
    outbox_codes,
    request_command,
    staff_row,
    world_with_registered_contact,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _expire_code(admin_conn: PgConnection, world: PartyRegistryWorld, contact_id: UUID) -> None:
    admin_conn.execute(
        "UPDATE request_engine.principal_contacts SET verification_expires_at = %s"
        " WHERE organization_id = %s AND id = %s",
        (datetime.now(UTC) - timedelta(minutes=1), world.organization_id, contact_id),
    )


@pytest.mark.asyncio
async def test_re_request_while_pending_is_rejected_without_side_effects(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    first = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    with pytest.raises(VerificationAlreadyPending) as caught:
        await commands.request_principal_contact_verification(
            request_command(world, contact.contact_id, key="req-2")
        )
    assert caught.value.expires_at == first.expires_at
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[4] == 0
    assert len(outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)) == 1


@pytest.mark.asyncio
async def test_request_after_expiry_issues_fresh_code_and_resets_attempts(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    _expire_code(admin_conn, world, contact.contact_id)
    reissued = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-2")
    )
    assert reissued.expires_at > datetime.now(UTC)
    assert len(outbox_codes(admin_conn, world.organization_id)) == 2
    row = staff_row(admin_conn, world.organization_id, contact.contact_id)
    assert row[3] is not None and row[3] > datetime.now(UTC)
    assert row[4] == 0


@pytest.mark.asyncio
async def test_expired_correct_code_never_confirms(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    code = outbox_codes(admin_conn, world.organization_id)[0]
    _expire_code(admin_conn, world, contact.contact_id)
    with pytest.raises(VerificationCodeExpired):
        await commands.confirm_principal_contact(
            confirm_command(world, contact.contact_id, code, key="confirm-late")
        )
    row = staff_row(admin_conn, world.organization_id, contact.contact_id)
    assert (row[0], row[4]) == (False, 0)
