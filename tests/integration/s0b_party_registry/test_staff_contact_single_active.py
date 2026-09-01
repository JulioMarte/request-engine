"""One active administrative contact per staff principal (0025 backstop).

`principal_contacts_one_active_per_principal_uq` is a partial unique index on
(organization_id, principal_id) WHERE active. The proof is sequential by
design: the INSERT is the only serialization point and the index is checked
atomically per statement, so there is no check-then-insert window to race —
the two-connection cédula race style would add nothing here. The direct-SQL
insert names the constraint; the real command maps the same violation to the
typed conflict.
"""

import psycopg
import pytest

from request_engine.modules.tenancy.application.commands import register_principal_contact
from request_engine.modules.tenancy.application.errors import PrincipalContactExists
from request_engine.platform.db.session import SessionFactory

from ._party_support import PgConnection
from ._staff_support import world_with_registered_contact

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_second_active_contact_is_rejected_with_the_named_backstop(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, _contact = await world_with_registered_contact(admin_conn, app_session_factory)
    with pytest.raises(psycopg.errors.UniqueViolation) as direct:
        admin_conn.execute(
            "INSERT INTO request_engine.principal_contacts"
            " (organization_id, principal_id, channel, normalized_value, active)"
            " VALUES (%s, %s, 'phone', '+18095550143', true)",
            (world.organization_id, world.operator_principal_id),
        )
    assert "principal_contacts_one_active_per_principal_uq" in str(direct.value)

    with pytest.raises(PrincipalContactExists):
        await commands.register_principal_contact(
            register_principal_contact.RegisterPrincipalContactCommand(
                organization_id=world.organization_id,
                principal_id=world.operator_principal_id,
                channel="phone",
                value="+1 809 555 0199",
                idempotency_key="register-second-active",
            )
        )
