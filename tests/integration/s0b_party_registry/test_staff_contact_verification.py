"""Staff administrative contact verification flow on real PostgreSQL (§9.2).

The register command creates the contact unverified; the verification
request stores a sha256 code hash with expiry, resets the attempt counter
and appends exactly ONE outbox event carrying the 6-digit code. Replay
returns the stored result without regenerating. Wrong codes consume
attempts until exhausted; a re-request issues a fresh code and resets
attempts; the correct code flips `verified` monotonically and clears the
code state; a further confirm is an idempotent success.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from request_engine.modules.tenancy.application.errors import (
    VerificationAttemptsExhausted,
    VerificationCodeInvalid,
)
from request_engine.platform.db.session import SessionFactory

from ._party_support import PgConnection, outbox_rows
from ._staff_support import (
    EVENT_TYPE,
    confirm_command,
    request_command,
    staff_row,
    world_with_registered_contact,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_request_verification_stores_hash_and_single_outbox_event(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    assert (contact.verified, contact.active) == (False, True)
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[:2] == (False, True)

    issued = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    assert issued.contact_id == contact.contact_id
    expected = datetime.now(UTC) + timedelta(minutes=15)
    assert abs((issued.expires_at - expected).total_seconds()) < 30
    events = outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)
    assert len(events) == 1
    payload = events[0]
    assert payload["principal_id"] == str(world.operator_principal_id)
    assert payload["contact_id"] == str(contact.contact_id)
    assert len(payload["code"]) == 6 and payload["code"].isdigit()
    code_hash = hashlib.sha256(payload["code"].encode()).hexdigest()
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[2] == code_hash

    replayed = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    assert replayed == issued
    assert len(outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)) == 1


@pytest.mark.asyncio
async def test_wrong_codes_exhaust_then_reissue_and_confirm(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    first_issued = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-1")
    )
    first_code = outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)[0]["code"]
    wrong = "000000" if first_code != "000000" else "000001"
    for remaining in (4, 3, 2, 1):
        with pytest.raises(VerificationCodeInvalid) as caught:
            await commands.confirm_principal_contact(
                confirm_command(world, contact.contact_id, wrong, key=f"wrong-{remaining}")
            )
        assert caught.value.attempts_remaining == remaining
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[4] == 4
    with pytest.raises(VerificationAttemptsExhausted):
        await commands.confirm_principal_contact(
            confirm_command(world, contact.contact_id, wrong, key="wrong-5")
        )
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[4] == 5

    reissued = await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-2")
    )
    assert reissued.expires_at > first_issued.expires_at
    codes = [row["code"] for row in outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)]
    assert len(codes) == 2 and codes[1] != first_code
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[4] == 0

    confirmed = await commands.confirm_principal_contact(
        confirm_command(world, contact.contact_id, codes[1], key="confirm-1")
    )
    assert confirmed.verified is True
    row = staff_row(admin_conn, world.organization_id, contact.contact_id)
    assert (row[0], row[2], row[3], row[4]) == (True, None, None, 0)
    again = await commands.confirm_principal_contact(
        confirm_command(world, contact.contact_id, "999999", key="confirm-2")
    )
    assert again.verified is True
    assert again.contact_id == contact.contact_id
