import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.organization_channel_policy_commands import (
    PostgresOrganizationChannelPolicyCommands,
)
from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as policy_commands,
)
from request_engine.modules.communications.application.errors import (
    OrganizationChannelPolicyRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency, pytest.mark.adversarial]


@pytest.mark.asyncio
async def test_first_channel_policy_creation_has_one_winner_and_revision_conflict_loser(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, principal, party = uuid4(), uuid4(), uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.organizations(id,organization_key,display_name) "
        "VALUES(%s,%s,'Clinic')",
        (organization, f"clinic-{organization}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.principals(id,organization_id,principal_kind,external_subject) "
        "VALUES(%s,%s,'agent',%s)",
        (principal, organization, str(principal)),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.parties(id,organization_id,party_kind,display_name) "
        "VALUES(%s,%s,'organization','Clinic authority')",
        (party, organization),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.principal_authority_grants "
        "(organization_id,principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational','communications.configure',%s,'operator','proof')",
        (organization, principal, principal),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.representations "
        "(organization_id,principal_id,represented_party_id,scope_key,authority_kind) "
        "VALUES(%s,%s,%s,'operations.manage_profile','delegated')",
        (organization, principal, party),
    )
    original_execute = AsyncSession.execute
    both_absent = asyncio.Event()
    connections: set[int] = set()

    async def paused_insert(
        session: AsyncSession, statement: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if "INSERT INTO request_engine.organization_channel_policies" in str(statement):
            # Owner has already observed no policy. Only pause, never fake the query/result.
            pid = (await original_execute(session, text("SELECT pg_backend_pid()"))).scalar_one()
            connections.add(pid)
            if len(connections) == 2:
                both_absent.set()
            await asyncio.wait_for(both_absent.wait(), 10)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", paused_insert)
    commands = PostgresOrganizationChannelPolicyCommands(command_session_factory)
    candidates = [
        policy_commands.SetOrganizationChannelPolicyCommand(
            organization_id=organization,
            principal_id=principal,
            authority_party_id=party,
            policy=policy_commands.OrganizationChannelPolicyInput(
                "appointment_confirmation", enabled, ("email",)
            ),
            expected_revision=0,
            idempotency_key=f"policy-first-{enabled}",
        )
        for enabled in (True, False)
    ]
    async with asyncio.timeout(15):
        results = await asyncio.gather(
            *(commands.set_organization_channel_policy(command) for command in candidates),
            return_exceptions=True,
        )
    assert len(connections) == 2
    winners = [result for result in results if not isinstance(result, BaseException)]
    losers = [result for result in results if isinstance(result, BaseException)]
    assert len(winners) == len(losers) == 1
    assert isinstance(losers[0], OrganizationChannelPolicyRevisionConflict)
    assert winners[0].revision == 1
    assert admin_conn.execute(
        "SELECT enabled,revision FROM request_engine.organization_channel_policies "
        "WHERE organization_id=%s",
        (organization,),
    ).fetchall() == [(winners[0].enabled, 1)]
    for table in ("idempotency_records", "audit_records"):
        assert admin_conn.execute(
            f"SELECT count(*) FROM request_engine.{table} WHERE organization_id=%s",
            (organization,),
        ).fetchone() == (1,)
    # The losing command's idempotency/audit effects rolled back, and winner replay is stable.
    winning_index = results.index(winners[0])
    assert await commands.set_organization_channel_policy(candidates[winning_index]) == winners[0]
