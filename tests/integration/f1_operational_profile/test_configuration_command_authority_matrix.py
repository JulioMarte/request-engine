"""Owner admission proof: real restricted-role writes, replay and withdrawal races.

A removed guard must fail fresh and completed-receipt cases; race orchestration
only pauses after the real DB admission and never replaces validation/write SQL.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import ModuleType
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from psycopg import Connection, sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import contextual_config_commands as config
from request_engine.modules.booking.adapters.db import (
    contextual_supply_lifecycle_commands as supply,
)
from request_engine.modules.booking.adapters.db import (
    contextual_terms_supersession_commands as terms,
)
from request_engine.modules.booking.adapters.db import resource_creation_commands as resources
from request_engine.modules.booking.adapters.db import (
    resource_schedule_exception_commands as exceptions,
)
from request_engine.modules.booking.application.commands.assign_resource_to_location import (
    AssignResourceToLocationCommand,
)
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    ConfigureBookingContextTermsCommand,
)
from request_engine.modules.booking.application.commands.create_resource import (
    CreateResourceCommand,
)
from request_engine.modules.booking.application.commands.retire_resource_location_assignment import (  # noqa: E501
    RetireResourceLocationAssignmentCommand,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
)
from request_engine.modules.booking.application.commands.set_resource_location_schedule_exception import (  # noqa: E501
    SetResourceLocationScheduleExceptionCommand,
)
from request_engine.modules.booking.application.commands.set_resource_schedule_exception import (
    SetResourceScheduleExceptionCommand,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
)
from request_engine.modules.catalog.adapters.db import (
    bootstrap_catalog_commands as catalog_bootstrap,
)
from request_engine.modules.catalog.adapters.db import location_creation_commands as locations
from request_engine.modules.catalog.adapters.db import operational_config_commands as hours
from request_engine.modules.catalog.adapters.db import operational_profile_commands as profile
from request_engine.modules.catalog.adapters.db import organization_holiday_commands as holidays
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    CreateOfferingCommand,
    CreateResourceCapabilityCommand,
    ReservationPolicyInput,
)
from request_engine.modules.catalog.application.commands.configure_offering_version_booking_terms import (  # noqa: E501
    ConfigureOfferingVersionBookingTermsCommand,
)
from request_engine.modules.catalog.application.commands.create_location import (
    CreateLocationCommand,
)
from request_engine.modules.catalog.application.commands.declare_organization_holidays import (
    DeclareOrganizationHolidaysCommand,
    OrganizationHolidayInput,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    SetLocationHoursExceptionCommand,
)
from request_engine.modules.catalog.application.commands.set_location_operational_hours import (
    LocationOperationalHoursInput,
    SetLocationOperationalHoursCommand,
)
from request_engine.modules.catalog.application.commands.set_location_public_contacts import (
    LocationPublicContactInput,
    SetLocationPublicContactsCommand,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    UpdateLocationOperationalInfoCommand,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.security.operational_authority import (
    OperationalAuthorityGrant,
    OperationalAuthorityRequired,
    require_operational_authority,
)

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.adversarial]
OPERATIONS = (
    "resource",
    "assignment",
    "retire",
    "availability",
    "assignment_exception",
    "resource_exception",
    "terms",
    "supersede_terms",
    "location",
    "location_profile",
    "location_contacts",
    "location_hours",
    "location_exception",
    "holidays",
    "capability",
    "offering",
    "base_terms",
)


@dataclass(frozen=True)
class Operation:
    adapter: ModuleType
    invoke: Callable[[], Coroutine[Any, Any, object]]


def _operation(
    name: str, conn: Connection[Any], factory: SessionFactory, world: F1ContextualScenario
) -> Operation:
    if name in {
        "location",
        "location_profile",
        "location_contacts",
        "location_hours",
        "location_exception",
        "holidays",
        "capability",
        "offering",
        "base_terms",
    }:
        return _catalog_operation(name, conn, factory, world)
    org, principal, party = world.organization_id, world.principal_id, world.authority_party_id
    key = f"authority-{uuid4().hex}"
    revision = conn.execute(
        "SELECT availability_revision FROM request_engine.resources WHERE id=%s",
        (world.resource_id,),
    ).fetchone()
    assert revision is not None
    rev = int(revision[0])
    start, end = datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 1, 2, tzinfo=UTC)
    if name == "resource":
        command = CreateResourceCommand(
            org, principal, party, world.location_id, key, "New doctor", "exclusive", 1, (), key
        )
        return Operation(
            resources,
            lambda: resources.PostgresResourceCreationCommands(factory).create_resource(command),
        )
    if name == "assignment":
        # A second valid resource avoids overlapping the scenario's assignment.
        row = conn.execute(
            "INSERT INTO request_engine.resources(organization_id,resource_key,display_name,"
            "capacity_model,capacity_units) VALUES(%s,%s,'Second doctor','exclusive',1) "
            "RETURNING id,availability_revision",
            (org, key),
        ).fetchone()
        assert row is not None
        command = AssignResourceToLocationCommand(
            org, principal, party, row[0], world.location_id, start, None, int(row[1]), key
        )
        return Operation(
            config,
            lambda: config.PostgresContextualConfigCommands(factory).assign_resource_to_location(
                command
            ),
        )
    if name == "retire":
        row = conn.execute(
            "SELECT revision FROM request_engine.resource_location_assignments WHERE id=%s",
            (world.assignment_id,),
        ).fetchone()
        assert row is not None
        command = RetireResourceLocationAssignmentCommand(
            org, principal, party, world.assignment_id, start, int(row[0]), rev, key
        )
        return Operation(
            supply,
            lambda: supply.PostgresContextualSupplyLifecycleCommands(
                factory
            ).retire_resource_location_assignment(command),
        )
    if name == "availability":
        command = SetResourceLocationAvailabilityCommand(
            org,
            principal,
            party,
            world.assignment_id,
            (ResourceLocationAvailabilityWindow(0, time(9), time(16)),),
            rev,
            key,
        )
        return Operation(
            supply,
            lambda: supply.PostgresContextualSupplyLifecycleCommands(
                factory
            ).set_resource_location_availability(command),
        )
    if name == "assignment_exception":
        command = SetResourceLocationScheduleExceptionCommand(
            org, principal, party, world.assignment_id, start, end, "unavailable", rev, key
        )
        return Operation(
            supply,
            lambda: supply.PostgresContextualSupplyLifecycleCommands(
                factory
            ).set_resource_location_schedule_exception(command),
        )
    if name == "resource_exception":
        command = SetResourceScheduleExceptionCommand(
            org, principal, party, world.resource_id, start, end, "unavailable", rev, key
        )
        return Operation(
            exceptions,
            lambda: exceptions.PostgresResourceScheduleExceptionCommands(
                factory
            ).set_resource_schedule_exception(command),
        )
    if name == "terms":
        # The existing price ends at cutover; new intent creates its own result.
        conn.execute(
            "UPDATE request_engine.booking_context_terms SET "
            "effective_during=tstzrange(lower(effective_during),%s,'[)') WHERE id=%s",
            (start, world.context_terms_id),
        )
        command = ConfigureBookingContextTermsCommand(
            org,
            principal,
            party,
            world.assignment_id,
            world.offering_version_id,
            start,
            None,
            Decimal("4500"),
            "DOP",
            45,
            True,
            key,
        )
        return Operation(
            config,
            lambda: config.PostgresContextualConfigCommands(
                factory
            ).configure_booking_context_terms(command),
        )
    row = conn.execute(
        "SELECT revision FROM request_engine.booking_context_terms WHERE id=%s",
        (world.context_terms_id,),
    ).fetchone()
    assert row is not None
    command = SupersedeBookingContextTermsCommand(
        org,
        principal,
        party,
        world.context_terms_id,
        int(row[0]),
        start,
        Decimal("4500"),
        "DOP",
        45,
        True,
        key,
    )
    return Operation(
        terms,
        lambda: terms.PostgresContextualTermsSupersessionCommands(
            factory
        ).supersede_booking_context_terms(command),
    )


def _catalog_operation(
    name: str, conn: Connection[Any], factory: SessionFactory, world: F1ContextualScenario
) -> Operation:
    org, principal, party = world.organization_id, world.principal_id, world.authority_party_id
    key = f"catalog-authority-{uuid4().hex}"
    row = conn.execute(
        "SELECT operational_revision FROM request_engine.locations WHERE id=%s",
        (world.location_id,),
    ).fetchone()
    assert row is not None
    revision = int(row[0])
    if name == "location":
        command = CreateLocationCommand(
            org, principal, party, key, "Second clinic", "America/Santo_Domingo", key
        )
        return Operation(
            locations,
            lambda: locations.PostgresLocationCreationCommands(factory).create_location(command),
        )
    if name == "location_profile":
        command = UpdateLocationOperationalInfoCommand(
            org,
            principal,
            party,
            world.location_id,
            "America/Santo_Domingo",
            True,
            revision,
            key,
            address_line1="10 Main Street",
        )
        return Operation(
            profile,
            lambda: profile.PostgresOperationalProfileCommands(
                factory
            ).update_location_operational_info(command),
        )
    if name == "location_contacts":
        command = SetLocationPublicContactsCommand(
            org,
            principal,
            party,
            world.location_id,
            (LocationPublicContactInput("email", "clinic@example.test"),),
            key,
        )
        return Operation(
            profile,
            lambda: profile.PostgresOperationalProfileCommands(
                factory
            ).set_location_public_contacts(command),
        )
    if name == "location_hours":
        command = SetLocationOperationalHoursCommand(
            org,
            principal,
            party,
            world.location_id,
            revision,
            (LocationOperationalHoursInput(0, time(9), time(16)),),
            key,
        )
        return Operation(
            hours,
            lambda: hours.PostgresOperationalConfigCommands(factory).set_location_operational_hours(
                command
            ),
        )
    if name == "location_exception":
        command = SetLocationHoursExceptionCommand(
            org,
            principal,
            party,
            world.location_id,
            datetime(2030, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 2, tzinfo=UTC),
            "unavailable",
            revision,
            key,
        )
        return Operation(
            profile,
            lambda: profile.PostgresOperationalProfileCommands(
                factory
            ).set_location_hours_exception(command),
        )
    if name == "holidays":
        command = DeclareOrganizationHolidaysCommand(
            org, principal, party, (OrganizationHolidayInput(date(2030, 1, 1), "New Year"),), key
        )
        return Operation(
            holidays,
            lambda: holidays.PostgresOrganizationHolidayCommands(
                factory
            ).declare_organization_holidays(command),
        )
    if name == "capability":
        command = CreateResourceCapabilityCommand(org, principal, party, key, "Pediatrics", key)
        return Operation(
            catalog_bootstrap,
            lambda: catalog_bootstrap.PostgresCatalogBootstrapCommands(
                factory
            ).create_resource_capability(command),
        )
    if name == "offering":
        command = CreateOfferingCommand(
            org,
            principal,
            party,
            key,
            "Consultation",
            None,
            30,
            True,
            True,
            15,
            (),
            ReservationPolicyInput(),
            key,
        )
        return Operation(
            catalog_bootstrap,
            lambda: catalog_bootstrap.PostgresCatalogBootstrapCommands(factory).create_offering(
                command
            ),
        )
    # Fresh OfferingVersion is a prerequisite, not the pricing result under test.
    offering = conn.execute(
        "INSERT INTO request_engine.offerings(organization_id,offering_key,display_name) "
        "VALUES(%s,%s,'Second consultation') RETURNING id",
        (org, key),
    ).fetchone()
    assert offering is not None
    version = conn.execute(
        "INSERT INTO request_engine.offering_versions(organization_id,offering_id,"
        "version,duration_minutes,bookable) VALUES(%s,%s,1,30,true) RETURNING id",
        (org, offering[0]),
    ).fetchone()
    assert version is not None
    command = ConfigureOfferingVersionBookingTermsCommand(
        org, principal, party, version[0], Decimal("4500"), "DOP", key
    )
    return Operation(
        profile,
        lambda: profile.PostgresOperationalProfileCommands(
            factory
        ).configure_offering_version_booking_terms(command),
    )


def _snapshot(conn: Connection[Any], world: F1ContextualScenario) -> object:
    # Full rows catch updates, range cutovers, revision bumps and negative effects,
    # not just row counts. Each new result must be produced by the real Command.
    snapshots: dict[str, object] = {}
    for table in (
        "resources",
        "resource_location_assignments",
        "booking_context_terms",
        "resource_location_availability",
        "resource_location_schedule_exceptions",
        "schedule_exceptions",
        "idempotency_records",
        "audit_records",
        "outbox_messages",
        "locations",
        "location_operational_hours",
        "location_public_contact_endpoints",
        "location_hours_exceptions",
        "resource_capabilities",
        "offerings",
        "offering_versions",
        "offering_resource_requirements",
        "offering_version_booking_terms",
        "offering_version_booking_policies",
    ):
        row = conn.execute(
            sql.SQL(
                "SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM {} t WHERE organization_id=%s"
            ).format(sql.Identifier("request_engine", table)),
            (world.organization_id,),
        ).fetchone()
        assert row is not None
        snapshots[table] = row[0]
    return snapshots


def _counts(conn: Connection[Any], world: F1ContextualScenario) -> tuple[int, int, int]:
    row = conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.idempotency_records "
        "WHERE organization_id=%s), (SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s), (SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s)",
        (world.organization_id,) * 3,
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


def _scope(name: str) -> str:
    if name in {"terms", "supersede_terms", "offering", "base_terms"}:
        return "operations.manage_terms"
    if name in {
        "resource",
        "assignment",
        "retire",
        "availability",
        "assignment_exception",
        "resource_exception",
    }:
        return "operations.manage_supply"
    return "operations.manage_profile"


def _withdraw(conn: Connection[Any], world: F1ContextualScenario, kind: str, name: str) -> None:
    if kind == "representation":
        conn.execute(
            "UPDATE request_engine.representations "
            "SET status='revoked',revision=revision+1 "
            "WHERE organization_id=%s AND principal_id=%s AND scope_key=%s",
            (world.organization_id, world.principal_id, _scope(name)),
        )
    elif kind == "party":
        conn.execute(
            "UPDATE request_engine.parties SET active=false WHERE id=%s",
            (world.authority_party_id,),
        )
    else:
        conn.execute(
            "UPDATE request_engine.principals SET active=false WHERE id=%s", (world.principal_id,)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.parametrize("kind", ("representation", "party", "principal"))
@pytest.mark.parametrize("replay", (False, True), ids=("fresh", "receipt_replay"))
async def test_configuration_command_rejects_withdrawn_authority_without_effects(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
    name: str,
    kind: str,
    replay: bool,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    operation = _operation(name, admin_conn, app_session_factory, world)
    if replay:
        initial = _counts(admin_conn, world)
        result = await operation.invoke()
        assert _counts(admin_conn, world) == (initial[0] + 1, initial[1] + 1, initial[2])
        succeeded = _snapshot(admin_conn, world)
        assert await operation.invoke() == result
        assert _snapshot(admin_conn, world) == succeeded
    _withdraw(admin_conn, world, kind, name)
    before = _snapshot(admin_conn, world)
    with pytest.raises(OperationalAuthorityRequired):
        await operation.invoke()
    assert _snapshot(admin_conn, world) == before


async def _blocked(observer: Connection[Any], holder: int) -> None:
    for _ in range(400):
        row = observer.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))", (holder,)
        ).fetchone()
        if row is not None and row[0] > 0:
            return
        await asyncio.sleep(0.01)
    pytest.fail("competing transaction did not reach the observed lock barrier")


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.parametrize("kind", ("representation", "party", "principal"))
@pytest.mark.parametrize("command_first", (False, True), ids=("withdrawal_wins", "command_wins"))
async def test_configuration_command_authority_withdrawal_serialization(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
    name: str,
    command_first: bool,
    kind: str,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    operation = _operation(name, admin_conn, app_session_factory, world)
    before = _snapshot(admin_conn, world)
    initial = _counts(admin_conn, world)
    admitted, release = asyncio.Event(), asyncio.Event()
    holder = 0

    async def pause_after_admission(
        session: AsyncSession, **kwargs: Any
    ) -> OperationalAuthorityGrant:
        nonlocal holder
        result = await require_operational_authority(session, **kwargs)
        holder = int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        admitted.set()
        await asyncio.wait_for(release.wait(), 10)
        return result

    async def revoke_in(session: AsyncSession) -> None:
        parameters = {
            "org": world.organization_id,
            "p": world.principal_id,
            "party": world.authority_party_id,
            "scope": _scope(name),
        }
        if kind == "representation":
            statement = (
                "UPDATE request_engine.representations SET status='revoked',revision=revision+1 "
                "WHERE organization_id=:org AND principal_id=:p AND scope_key=:scope"
            )
        elif kind == "party":
            statement = "UPDATE request_engine.parties SET active=false WHERE id=:party"
        else:
            statement = "UPDATE request_engine.principals SET active=false WHERE id=:p"
        await session.execute(text(statement), parameters)

    async def revoke() -> None:
        async with tenant_transaction(app_session_factory, world.organization_id) as session:
            await revoke_in(session)

    if command_first:
        with patch.object(
            operation.adapter, "require_operational_authority", pause_after_admission
        ):
            command = asyncio.create_task(operation.invoke())
            revoker: asyncio.Task[None] | None = None
            try:
                await asyncio.wait_for(admitted.wait(), 10)
                revoker = asyncio.create_task(revoke())
                await _blocked(admin_conn, holder)
                assert not revoker.done()
            finally:
                release.set()
                await asyncio.wait_for(command, 15)
                if revoker is not None:
                    await asyncio.wait_for(revoker, 15)
        assert _snapshot(admin_conn, world) != before
        assert _counts(admin_conn, world) == (initial[0] + 1, initial[1] + 1, initial[2])
        after = _snapshot(admin_conn, world)
        with pytest.raises(OperationalAuthorityRequired):
            await operation.invoke()
        assert _snapshot(admin_conn, world) == after
    else:
        async with tenant_transaction(app_session_factory, world.organization_id) as session:
            await revoke_in(session)
            holder = int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
            command = asyncio.create_task(operation.invoke())
            try:
                await _blocked(admin_conn, holder)
                assert not command.done()
            except BaseException:
                command.cancel()
                await asyncio.gather(command, return_exceptions=True)
                raise
        with pytest.raises(OperationalAuthorityRequired):
            await asyncio.wait_for(command, 15)
        assert _snapshot(admin_conn, world) == before
