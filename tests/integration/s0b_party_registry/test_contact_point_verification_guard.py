"""I-S0b-4 (backstop): downward verification is rejected by the database.

`request_engine_app` holds UPDATE privileges on `party_contact_points`, so a
raw `verified = false` downgrade would otherwise be allowed by grants alone.
The 0023 guard trigger rejects it with SQLSTATE 23514 even through the real
runtime application role, keeping verification monotone under direct SQL and
not only through the confirm command.
"""

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.platform.db.session import SessionFactory

from ._party_commands import verified_operator_contact_point
from ._party_support import PgConnection, contact_point_row

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_runtime_role_cannot_downgrade_verification(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world, _party, contact = await verified_operator_contact_point(admin_conn, app_session_factory)
    async with app_session_factory() as session:
        await session.execute(
            text("SELECT set_config('request_engine.organization_id', :org, true)"),
            {"org": str(world.organization_id)},
        )
        with pytest.raises(IntegrityError) as caught:
            await session.execute(
                text(
                    "UPDATE request_engine.party_contact_points SET verified = false WHERE id = :cp"
                ),
                {"cp": str(contact.contact_point_id)},
            )
    assert "monotone" in str(caught.value)
    row = contact_point_row(admin_conn, world.organization_id, contact.contact_point_id)
    assert row[0] is True


@pytest.mark.asyncio
async def test_privileged_connection_cannot_downgrade_verification(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world, _party, contact = await verified_operator_contact_point(admin_conn, app_session_factory)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.party_contact_points SET verified = false WHERE id = %s",
            (contact.contact_point_id,),
        )
    row = contact_point_row(admin_conn, world.organization_id, contact.contact_point_id)
    assert row[0] is True
