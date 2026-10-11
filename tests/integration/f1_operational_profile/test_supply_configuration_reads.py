import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import supply_configuration_reader as supply_adapter
from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.adapters.db.resource_schedule_exception_commands import (
    PostgresResourceScheduleExceptionCommands,
)
from request_engine.modules.booking.adapters.db.supply_configuration_reader import (
    PostgresSupplyConfigurationReader,
)
from request_engine.modules.booking.application.commands import (
    set_resource_location_schedule_exception as context_exceptions,
)
from request_engine.modules.booking.application.commands import (
    set_resource_schedule_exception as resource_exceptions,
)
from request_engine.modules.booking.application.queries.supply_configuration import (
    SupplyConfigurationQuery,
)
from request_engine.modules.communications.adapters.db import (
    channel_configuration_reader as channel_adapter,
)
from request_engine.modules.communications.adapters.db.channel_configuration_reader import (
    PostgresChannelConfigurationReader,
)
from request_engine.modules.communications.adapters.db.organization_channel_policy_commands import (
    PostgresOrganizationChannelPolicyCommands,
)
from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as channel_commands,
)
from request_engine.modules.communications.application.queries.channel_configuration import (
    ChannelConfigurationQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    OperationalAuthorityGrant,
    OperationalAuthorityRequired,
    require_principal_serialized_operational_authority,
)
from request_engine.platform.security.principal_authority import CapabilityRequired

from .dummy_data import create_contextual_cardiology_scenario

pytestmark = [pytest.mark.postgres, pytest.mark.adversarial, pytest.mark.security]


def _grant_read(conn: Connection[Any], organization: object, principal: object, key: str) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id,"
        "principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational',%s,%s,'operator','configuration read grant')",
        (organization, principal, key, principal),
    )


async def _observe_principal_wait(conn: Connection[Any], holder_pid: int) -> None:
    async with asyncio.timeout(10):
        while True:
            blocked = conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND %s=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock'",
                (holder_pid,),
            ).fetchone()
            if blocked is not None and blocked[0] > 0:
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_configuration_reads_reconstruct_current_revisions_and_keep_foreign_ids_opaque(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    reader = PostgresSupplyConfigurationReader(app_session_factory)
    query = SupplyConfigurationQuery(
        world.organization_id, world.principal_id, world.authority_party_id, limit=1
    )
    resources = await reader.read_resources(query)
    assert len(resources) == 1
    assert resources[0].resource_id == world.resource_id
    assert resources[0].availability_revision > 0
    assert len(resources[0].capability_ids) == 1
    assignments = await reader.read_assignments(query)
    assert assignments[0].assignment_id == world.assignment_id
    assert assignments[0].resource_availability_revision == resources[0].availability_revision
    terms = await reader.read_terms(query)
    assert terms[0].context_terms_id == world.context_terms_id
    assert terms[0].revision == 1
    windows = await reader.read_availability(replace(query, assignment_id=world.assignment_id))
    assert windows[0].weekday == 0
    assert windows[0].local_start.hour == 9
    assert await reader.read_resources(replace(query, resource_id=other.resource_id)) == ()
    assert await reader.read_assignments(replace(query, assignment_id=other.assignment_id)) == ()
    assert await reader.read_exceptions(replace(query, assignment_id=world.assignment_id)) == ()
    with pytest.raises(OperationalAuthorityRequired):
        await reader.read_resources(replace(query, authority_party_id=other.authority_party_id))


@pytest.mark.asyncio
async def test_channel_read_exposes_missing_revision_zero_and_rejects_false_authority(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    reader = PostgresChannelConfigurationReader(app_session_factory)
    _grant_read(
        admin_conn, world.organization_id, world.principal_id, "communications.read_configuration"
    )
    query = ChannelConfigurationQuery(
        world.organization_id,
        world.principal_id,
        world.authority_party_id,
        "appointment_confirmation",
    )
    result = await reader.read_configuration(query)
    assert not result.configured
    assert result.revision == 0
    assert result.enabled is None and result.channel_policy is None
    _grant_read(admin_conn, world.organization_id, world.principal_id, "communications.configure")
    commands = PostgresOrganizationChannelPolicyCommands(app_session_factory)
    changed = await commands.set_organization_channel_policy(
        channel_commands.SetOrganizationChannelPolicyCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            authority_party_id=world.authority_party_id,
            policy=channel_commands.OrganizationChannelPolicyInput(
                "appointment_confirmation", True, ("email",)
            ),
            expected_revision=result.revision,
            idempotency_key="read-then-configure",
        )
    )
    reread = await reader.read_configuration(query)
    assert reread.configured and reread.enabled
    assert reread.revision == changed.revision == 1
    assert reread.channel_policy is not None
    assert reread.channel_policy["channels"] == ["email"]
    with pytest.raises(OperationalAuthorityRequired):
        await reader.read_configuration(replace(query, authority_party_id=uuid4()))


@pytest.mark.asyncio
async def test_supply_keyset_foreign_filters_and_withdrawn_authority(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    second_id = uuid4()
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    admin_conn.execute(
        "INSERT INTO request_engine.resources "
        "(id,organization_id,resource_key,display_name,capacity_model,capacity_units) "
        "VALUES (%s,%s,'second-doctor','Second doctor','exclusive',1)",
        (second_id, world.organization_id),
    )
    reader = PostgresSupplyConfigurationReader(app_session_factory)
    query = SupplyConfigurationQuery(
        world.organization_id, world.principal_id, world.authority_party_id, limit=1
    )
    ordered_ids = sorted([world.resource_id, second_id])
    first = await reader.read_resources(query)
    assert [row.resource_id for row in first] == ordered_ids  # Actual SQL lookahead.
    last = await reader.read_resources(replace(query, after=first[0].resource_id))
    assert [row.resource_id for row in last] == ordered_ids[1:]
    assert await reader.read_resources(replace(query, after=last[0].resource_id)) == ()
    assert await reader.read_terms(replace(query, assignment_id=other.assignment_id)) == ()
    assert await reader.read_availability(replace(query, assignment_id=other.assignment_id)) == ()
    with pytest.raises(CapabilityRequired):
        await reader.read_resources(replace(query, principal_id=other.principal_id))
    admin_conn.execute(
        "UPDATE request_engine.representations SET status='revoked' "
        "WHERE organization_id=%s AND principal_id=%s AND scope_key='operations.manage_supply'",
        (world.organization_id, world.principal_id),
    )
    with pytest.raises(OperationalAuthorityRequired):
        await reader.read_resources(query)


@pytest.mark.asyncio
async def test_exception_readback_after_authoritative_commands(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    reader = PostgresSupplyConfigurationReader(app_session_factory)
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    query = SupplyConfigurationQuery(
        world.organization_id, world.principal_id, world.authority_party_id
    )
    initial_revision = (await reader.read_resources(query))[0].availability_revision
    start = datetime(2026, 8, 17, 13, tzinfo=UTC)
    end = datetime(2026, 8, 17, 14, tzinfo=UTC)
    context = await context_exceptions.set_resource_location_schedule_exception(
        PostgresContextualSupplyLifecycleCommands(app_session_factory),
        context_exceptions.SetResourceLocationScheduleExceptionCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            authority_party_id=world.authority_party_id,
            assignment_id=world.assignment_id,
            start_at=start,
            end_at=end,
            exception_kind="unavailable",
            expected_resource_availability_revision=initial_revision,
            idempotency_key="context-absence",
            reason="Clinic meeting",
        ),
    )
    resource = await resource_exceptions.set_resource_schedule_exception(
        PostgresResourceScheduleExceptionCommands(app_session_factory),
        resource_exceptions.SetResourceScheduleExceptionCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            authority_party_id=world.authority_party_id,
            resource_id=world.resource_id,
            start_at=start,
            end_at=end,
            exception_kind="unavailable",
            expected_resource_availability_revision=context.resource_availability_revision,
            idempotency_key="resource-absence",
            reason="Doctor absence",
        ),
    )
    context_rows = await reader.read_exceptions(replace(query, assignment_id=world.assignment_id))
    resource_rows = await reader.read_exceptions(replace(query, resource_id=world.resource_id))
    assert len(context_rows) == len(resource_rows) == 1
    assert context_rows[0].exception_id == context.exception_id
    assert context_rows[0].assignment_id == world.assignment_id
    assert context_rows[0].reason == "Clinic meeting"
    assert resource_rows[0].exception_id == resource.exception_id
    assert resource_rows[0].assignment_id is None
    assert resource_rows[0].start_at == start and resource_rows[0].end_at == end
    assert resource_rows[0].reason == "Doctor absence"
    assert context_rows[0].active and resource_rows[0].active
    assert context_rows[0].resource_availability_revision == resource.resource_availability_revision
    assert (
        resource_rows[0].resource_availability_revision == resource.resource_availability_revision
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["booking", "communications"])
async def test_configuration_read_rechecks_standing_grant_not_only_representation(
    admin_conn: Connection[Any], app_session_factory: SessionFactory, surface: str
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    capability = (
        "booking.read_supply" if surface == "booking" else "communications.read_configuration"
    )
    _grant_read(admin_conn, world.organization_id, world.principal_id, capability)
    booking = PostgresSupplyConfigurationReader(app_session_factory)
    channels = PostgresChannelConfigurationReader(app_session_factory)
    supply_query = SupplyConfigurationQuery(
        world.organization_id, world.principal_id, world.authority_party_id
    )
    channel_query = ChannelConfigurationQuery(
        world.organization_id,
        world.principal_id,
        world.authority_party_id,
        "appointment_confirmation",
    )
    if surface == "booking":
        assert await booking.read_resources(supply_query)
    else:
        assert not (await channels.read_configuration(channel_query)).configured
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked',revision=revision+1,"
        "revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key=%s",
        (world.principal_id, world.principal_id, capability),
    )
    with pytest.raises(CapabilityRequired):
        if surface == "booking":
            await booking.read_resources(supply_query)
        else:
            await channels.read_configuration(channel_query)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations WHERE organization_id=%s "
        "AND principal_id=%s AND status='active'",
        (world.organization_id, world.principal_id),
    ).fetchone() == (3,)


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_grant_revocation_winning_principal_root_denies_waiting_configuration_read(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    reader = PostgresSupplyConfigurationReader(app_session_factory)
    query = SupplyConfigurationQuery(
        world.organization_id, world.principal_id, world.authority_party_id
    )
    with psycopg.connect(admin_conn.info.dsn) as revoker:
        revoker.execute(
            "UPDATE request_engine.principal_authority_grants SET status='revoked',"
            "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
            "WHERE principal_id=%s AND capability_key='booking.read_supply'",
            (world.principal_id, world.principal_id),
        )
        reading = asyncio.create_task(reader.read_resources(query))
        try:
            await _observe_principal_wait(admin_conn, revoker.info.backend_pid)
            assert not reading.done()
        finally:
            revoker.commit()
        with pytest.raises(CapabilityRequired):
            await reading


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_configuration_authority_winning_root_finishes_before_grant_revocation(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    started = threading.Event()

    def revoke() -> None:
        with psycopg.connect(admin_conn.info.dsn) as revoker:
            started.set()
            revoker.execute(
                "UPDATE request_engine.principal_authority_grants SET status='revoked',"
                "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
                "WHERE principal_id=%s AND capability_key='booking.read_supply'",
                (world.principal_id, world.principal_id),
            )

    revoking: asyncio.Task[None] | None = None
    try:
        async with tenant_transaction(app_session_factory, world.organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                capability="booking.read_supply",
            )
            holder = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            revoking = asyncio.create_task(asyncio.to_thread(revoke))
            assert await asyncio.to_thread(started.wait, 10)
            await _observe_principal_wait(admin_conn, holder)
            assert not revoking.done()
            result = await session.execute(
                text("SELECT id FROM request_engine.resources WHERE organization_id=:org"),
                {"org": world.organization_id},
            )
            assert result.scalar_one() == world.resource_id
    finally:
        if revoking is not None:
            await revoking
    with pytest.raises(CapabilityRequired):
        await PostgresSupplyConfigurationReader(app_session_factory).read_resources(
            SupplyConfigurationQuery(
                world.organization_id, world.principal_id, world.authority_party_id
            )
        )


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("surface", ["booking", "communications"])
async def test_principal_root_read_does_not_deadlock_with_representation_row_writer(
    admin_conn: Connection[Any], app_session_factory: SessionFactory, surface: str
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    capability = (
        "booking.read_supply" if surface == "booking" else "communications.read_configuration"
    )
    _grant_read(admin_conn, world.organization_id, world.principal_id, capability)
    scope = "operations.manage_supply" if surface == "booking" else "operations.manage_profile"
    revoker_pid = asyncio.get_running_loop().create_future()
    holder_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    proceed = asyncio.Event()

    async def admitted(
        session: AsyncSession, *, organization_id: UUID, principal_id: UUID, capability: str
    ) -> None:
        # Pause only scheduling, not business outcomes: execute the real current
        # grant check and continue the real owner reader on that SAME connection.
        await require_current_tenant_capability(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            capability=capability,
        )
        holder_pid.set_result((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await asyncio.wait_for(proceed.wait(), 10)

    async def revoke() -> None:
        # Real runtime UPDATE is permitted by the existing narrow tenant role.
        # Its trigger holds the Representation row and then waits for Principal.
        async with tenant_transaction(app_session_factory, world.organization_id) as session:
            pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            revoker_pid.set_result(pid)
            await session.execute(
                text(
                    "UPDATE request_engine.representations "
                    "SET status='revoked',revision=revision+1 "
                    "WHERE organization_id=:o AND principal_id=:p AND scope_key=:s"
                ),
                {"o": world.organization_id, "p": world.principal_id, "s": scope},
            )

    async def read() -> None:
        if surface == "booking":
            rows = await PostgresSupplyConfigurationReader(app_session_factory).read_resources(
                SupplyConfigurationQuery(
                    world.organization_id, world.principal_id, world.authority_party_id
                )
            )
            assert rows[0].resource_id == world.resource_id
        else:
            result = await PostgresChannelConfigurationReader(
                app_session_factory
            ).read_configuration(
                ChannelConfigurationQuery(
                    world.organization_id,
                    world.principal_id,
                    world.authority_party_id,
                    "appointment_confirmation",
                )
            )
            assert not result.configured

    revoking: asyncio.Task[None] | None = None
    adapter = supply_adapter if surface == "booking" else channel_adapter
    with patch.object(adapter, "require_current_tenant_capability", side_effect=admitted):
        reading = asyncio.create_task(read())
        try:
            holder = await asyncio.wait_for(holder_pid, 10)
            revoking = asyncio.create_task(revoke())
            writer = await asyncio.wait_for(revoker_pid, 10)
            await _observe_principal_wait(admin_conn, holder)
            assert admin_conn.execute(
                "SELECT %s=ANY(pg_blocking_pids(%s))", (holder, writer)
            ).fetchone() == (True,)
            assert not revoking.done()
            proceed.set()
            async with asyncio.timeout(10):
                await reading
        finally:
            proceed.set()
            await asyncio.wait_for(asyncio.gather(reading, return_exceptions=True), 10)
            if revoking is not None:
                await asyncio.wait_for(revoking, 10)
    with pytest.raises(OperationalAuthorityRequired):
        await read()
    assert admin_conn.execute(
        "SELECT status FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND capability_key=%s",
        (world.principal_id, capability),
    ).fetchone() == ("active",)


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("surface", ["booking", "communications"])
async def test_representation_writer_winning_principal_denies_waiting_configuration_read(
    admin_conn: Connection[Any], app_session_factory: SessionFactory, surface: str
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    capability = (
        "booking.read_supply" if surface == "booking" else "communications.read_configuration"
    )
    _grant_read(admin_conn, world.organization_id, world.principal_id, capability)
    scope = "operations.manage_supply" if surface == "booking" else "operations.manage_profile"

    async def read() -> None:
        if surface == "booking":
            await PostgresSupplyConfigurationReader(app_session_factory).read_resources(
                SupplyConfigurationQuery(
                    world.organization_id, world.principal_id, world.authority_party_id
                )
            )
        else:
            await PostgresChannelConfigurationReader(app_session_factory).read_configuration(
                ChannelConfigurationQuery(
                    world.organization_id,
                    world.principal_id,
                    world.authority_party_id,
                    "appointment_confirmation",
                )
            )

    reading: asyncio.Task[None] | None = None
    async with tenant_transaction(app_session_factory, world.organization_id) as writer:
        # Actual restricted-role UPDATE completes its trigger and holds P before
        # the independent owner read starts. Commit, not scheduling time, decides.
        await writer.execute(
            text(
                "UPDATE request_engine.representations SET status='revoked',revision=revision+1 "
                "WHERE organization_id=:o AND principal_id=:p AND scope_key=:s"
            ),
            {"o": world.organization_id, "p": world.principal_id, "s": scope},
        )
        holder = (await writer.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        reading = asyncio.create_task(read())
        await _observe_principal_wait(admin_conn, holder)
        assert not reading.done()
    with pytest.raises(OperationalAuthorityRequired):
        async with asyncio.timeout(10):
            await reading


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["booking", "communications"])
async def test_inactive_authority_party_denies_configuration_with_live_grant_and_representation(
    admin_conn: Connection[Any], app_session_factory: SessionFactory, surface: str
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    capability = (
        "booking.read_supply" if surface == "booking" else "communications.read_configuration"
    )
    _grant_read(admin_conn, world.organization_id, world.principal_id, capability)
    async with tenant_transaction(app_session_factory, world.organization_id) as writer:
        await writer.execute(
            text(
                "UPDATE request_engine.parties SET active=false WHERE organization_id=:o AND id=:p"
            ),
            {"o": world.organization_id, "p": world.authority_party_id},
        )
    with pytest.raises(OperationalAuthorityRequired):
        if surface == "booking":
            await PostgresSupplyConfigurationReader(app_session_factory).read_resources(
                SupplyConfigurationQuery(
                    world.organization_id, world.principal_id, world.authority_party_id
                )
            )
        else:
            await PostgresChannelConfigurationReader(app_session_factory).read_configuration(
                ChannelConfigurationQuery(
                    world.organization_id,
                    world.principal_id,
                    world.authority_party_id,
                    "appointment_confirmation",
                )
            )
    representations = admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations "
        "WHERE principal_id=%s AND represented_party_id=%s AND status='active'",
        (world.principal_id, world.authority_party_id),
    ).fetchone()
    assert representations is not None and representations[0] > 0


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("reader_first", [True, False])
async def test_party_deactivation_serializes_configuration_admission(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    reader_first: bool,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    _grant_read(admin_conn, world.organization_id, world.principal_id, "booking.read_supply")
    ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    release = asyncio.Event()

    async def admitted(
        session: AsyncSession,
        *,
        organization_id: UUID,
        principal_id: UUID,
        authority_party_id: UUID,
        scope_key: str,
    ) -> OperationalAuthorityGrant:
        # Only pause after the actual owner connection has admitted authority.
        result = await require_principal_serialized_operational_authority(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            authority_party_id=authority_party_id,
            scope_key=scope_key,
        )
        ready.set_result((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await asyncio.wait_for(release.wait(), 10)
        return result

    async def read() -> None:
        rows = await PostgresSupplyConfigurationReader(app_session_factory).read_resources(
            SupplyConfigurationQuery(
                world.organization_id, world.principal_id, world.authority_party_id
            )
        )
        assert [row.resource_id for row in rows] == [world.resource_id]

    async def deactivate() -> None:
        async with tenant_transaction(app_session_factory, world.organization_id) as session:
            await session.execute(
                text(
                    "UPDATE request_engine.parties SET active=false "
                    "WHERE organization_id=:o AND id=:p"
                ),
                {"o": world.organization_id, "p": world.authority_party_id},
            )

    if reader_first:
        monkeypatch.setattr(
            supply_adapter, "require_principal_serialized_operational_authority", admitted
        )
        reading = asyncio.create_task(read())
        writing: asyncio.Task[None] | None = None
        try:
            holder = await asyncio.wait_for(ready, 10)
            writing = asyncio.create_task(deactivate())
            await _observe_principal_wait(admin_conn, holder)
            assert not writing.done()
        finally:
            release.set()
            try:
                await asyncio.wait_for(reading, 10)
            finally:
                if writing is not None:
                    await asyncio.wait_for(writing, 10)
        monkeypatch.undo()
    else:
        async with tenant_transaction(app_session_factory, world.organization_id) as writer:
            await writer.execute(
                text(
                    "UPDATE request_engine.parties SET active=false "
                    "WHERE organization_id=:o AND id=:p"
                ),
                {"o": world.organization_id, "p": world.authority_party_id},
            )
            holder = (await writer.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            reading = asyncio.create_task(read())
            await _observe_principal_wait(admin_conn, holder)
            assert not reading.done()
        with pytest.raises(OperationalAuthorityRequired):
            async with asyncio.timeout(10):
                await reading
    with pytest.raises(OperationalAuthorityRequired):
        await read()
    assert admin_conn.execute(
        "SELECT active FROM request_engine.parties WHERE id=%s", (world.authority_party_id,)
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations "
        "WHERE principal_id=%s AND status='active'",
        (world.principal_id,),
    ).fetchone() == (3,)
