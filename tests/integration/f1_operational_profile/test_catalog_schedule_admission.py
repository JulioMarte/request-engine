"""HTTP plus real app-role owner admission: caller errors never become partial facts."""

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response
from psycopg import Connection

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.booking.adapters.db.contextual_config_commands import (
    PostgresContextualConfigCommands,
)
from request_engine.modules.booking.adapters.db.contextual_terms_supersession_commands import (
    PostgresContextualTermsSupersessionCommands,
)
from request_engine.modules.booking.api.operational_terms_router import (
    create_operational_terms_router,
)
from request_engine.modules.booking.application.commands import (
    configure_booking_context_terms as booking_configure,
)
from request_engine.modules.booking.application.commands import (
    supersede_booking_context_terms as booking_supersede,
)
from request_engine.modules.booking.application.operational_errors import BookingTermsInvalidInput
from request_engine.modules.catalog.adapters.db.operational_config_commands import (
    PostgresOperationalConfigCommands,
)
from request_engine.modules.catalog.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.catalog.api.operational_errors import catalog_operational_error_handler
from request_engine.modules.catalog.api.operational_schedule_router import (
    create_operational_schedule_router,
)
from request_engine.modules.catalog.application.commands.configure_offering_version_booking_terms import (  # noqa: E501
    ConfigureOfferingVersionBookingTermsCommand,
    configure_offering_version_booking_terms,
)
from request_engine.modules.catalog.application.commands.declare_organization_holidays import (
    DeclareOrganizationHolidaysHandler,
)
from request_engine.modules.catalog.application.commands.set_location_operational_hours import (
    LocationOperationalHoursInput,
    SetLocationOperationalHoursCommand,
    set_location_operational_hours,
)
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    CatalogInvalidInput,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .dummy_data import create_contextual_cardiology_scenario
from .test_operational_commands import operational_authority_fixture

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.adversarial]


class _ActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.actor


def _app(actor: ActorContext, sessions: SessionFactory) -> FastAPI:
    app = FastAPI()
    add_global_error_handlers(app)
    app.add_exception_handler(CatalogConfigurationConflict, catalog_operational_error_handler)
    profile = PostgresOperationalProfileCommands(sessions)
    app.include_router(
        create_operational_schedule_router(
            hours_handler=PostgresOperationalConfigCommands(sessions),
            exception_handler=profile,
            terms_handler=profile,
            holidays_handler=cast(DeclareOrganizationHolidaysHandler, object()),
            actor_resolver=_ActorResolver(actor),
        )
    )
    app.include_router(
        create_operational_terms_router(
            configure_handler=PostgresContextualConfigCommands(sessions),
            supersede_handler=PostgresContextualTermsSupersessionCommands(sessions),
            actor_resolver=_ActorResolver(actor),
        )
    )
    return app


def _facts(conn: Connection[Any]) -> tuple[object, ...]:
    return tuple(
        conn.execute(query).fetchall()
        for query in (
            "SELECT count(*) FROM request_engine.location_operational_hours",
            "SELECT count(*) FROM request_engine.offering_version_booking_terms",
            "SELECT count(*) FROM request_engine.idempotency_records",
            "SELECT count(*) FROM request_engine.audit_records",
            "SELECT count(*) FROM request_engine.outbox_messages",
            "SELECT id,operational_revision FROM request_engine.locations ORDER BY id",
            "SELECT id,amount,effective_during,revision FROM request_engine.booking_context_terms "
            "ORDER BY id",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "window",
    [
        {"weekday": 99, "local_start": "08:00:00", "local_end": "17:00:00"},
        {"weekday": 0, "local_start": "17:00:00", "local_end": "08:00:00"},
        {"weekday": 0, "local_start": "08:00:00Z", "local_end": "17:00:00Z"},
        {
            "weekday": 0,
            "local_start": "08:00:00",
            "local_end": "17:00:00",
            "valid_from": "2026-10-10",
            "valid_until": "2026-10-09",
        },
    ],
)
async def test_invalid_hours_http_has_no_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    window: dict[str, object],
) -> None:
    org, party, principal, _, location = operational_authority_fixture(admin_conn)
    before = _facts(admin_conn)
    app = _app(ActorContext(org, principal, frozenset({"catalog.manage"})), session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        result = await client.put(
            f"/v1/operations/locations/{location}/hours",
            headers={"Idempotency-Key": "invalid-hours"},
            json={
                "authority_party_id": str(party),
                "expected_operational_revision": 1,
                "windows": [window],
            },
        )
    assert result.status_code == 422, result.text
    assert result.json()["error"]["code"] == "validation_failed"
    assert _facts(admin_conn) == before


@pytest.mark.asyncio
async def test_missing_and_foreign_location_have_same_owner_conflict_without_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
) -> None:
    org, party, principal, _, _ = operational_authority_fixture(admin_conn)
    foreign_location = operational_authority_fixture(admin_conn)[4]
    before = _facts(admin_conn)
    app = _app(ActorContext(org, principal, frozenset({"catalog.manage"})), session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        responses: list[Response] = []
        for target in (uuid4(), foreign_location):
            responses.append(
                await client.put(
                    f"/v1/operations/locations/{target}/hours",
                    headers={"Idempotency-Key": str(target)},
                    json={
                        "authority_party_id": str(party),
                        "expected_operational_revision": 1,
                        "windows": [{"weekday": 0, "local_start": "08:00", "local_end": "17:00"}],
                    },
                )
            )
    assert [response.status_code for response in responses] == [409, 409]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["error"]["code"] == "catalog_configuration_conflict"
    assert _facts(admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount",
    ["1.0000001", "100000000000000", "NaN", "-1", "0E-999999999", "0E+999999999"],
)
async def test_invalid_price_http_and_owner_reject_without_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    amount: str,
) -> None:
    org, party, principal, _, _ = operational_authority_fixture(admin_conn)
    before = _facts(admin_conn)
    target = uuid4()
    app = _app(ActorContext(org, principal, frozenset({"catalog.manage"})), session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        result = await client.put(
            f"/v1/operations/offering-versions/{target}/booking-terms",
            headers={"Idempotency-Key": "invalid-terms"},
            json={
                "authority_party_id": str(party),
                "amount": amount,
                "currency": "USD",
            },
        )
    assert result.status_code == 422, result.text
    assert result.json()["error"]["code"] == "validation_failed"
    command = ConfigureOfferingVersionBookingTermsCommand(
        org, principal, party, target, Decimal(amount), "USD", "invalid-direct-terms"
    )
    profile = PostgresOperationalProfileCommands(session_factory)
    with pytest.raises(CatalogInvalidInput):
        await configure_offering_version_booking_terms(profile, command)
    with pytest.raises(CatalogInvalidInput):
        await profile.configure_offering_version_booking_terms(command)
    assert _facts(admin_conn) == before


@pytest.mark.asyncio
async def test_duplicate_hours_typed_owner_error_without_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
) -> None:
    org, party, principal, _, location = operational_authority_fixture(admin_conn)
    before = _facts(admin_conn)
    window = LocationOperationalHoursInput(0, time(8), time(17))
    command = SetLocationOperationalHoursCommand(
        org, principal, party, location, 1, (window, window), "duplicate-hours"
    )
    handler = PostgresOperationalConfigCommands(session_factory)
    with pytest.raises(CatalogInvalidInput, match="duplicate"):
        await set_location_operational_hours(handler, command)
    with pytest.raises(CatalogInvalidInput, match="duplicate"):
        await handler.set_location_operational_hours(command)
    assert _facts(admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["99999999999999.999999", "1.0000000", "0.0000000", 19])
async def test_max_precision_price_receipt_matches_stored_amount_and_replay(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    amount: str | int,
) -> None:
    org, party, principal, _, _ = operational_authority_fixture(admin_conn)
    admin_conn.execute(
        """
        INSERT INTO request_engine.representations
            (organization_id,principal_id,represented_party_id,scope_key,authority_kind)
        VALUES(%s,%s,%s,'operations.manage_terms','delegated')
    """,
        (org, principal, party),
    )
    offering = admin_conn.execute(
        """
        INSERT INTO request_engine.offerings(organization_id,offering_key,display_name)
        VALUES(%s,%s,'Precision proof') RETURNING id
    """,
        (org, uuid4().hex),
    ).fetchone()
    assert offering is not None
    version = admin_conn.execute(
        """
        INSERT INTO request_engine.offering_versions
            (organization_id,offering_id,version,duration_minutes)
        VALUES(%s,%s,1,30) RETURNING id
    """,
        (org, offering[0]),
    ).fetchone()
    assert version is not None
    target = cast(UUID, version[0])
    app = _app(ActorContext(org, principal, frozenset({"catalog.manage"})), session_factory)
    payload = {
        "authority_party_id": str(party),
        "amount": amount,
        "currency": "USD",
    }
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        first = await client.put(
            f"/v1/operations/offering-versions/{target}/booking-terms",
            headers={"Idempotency-Key": "exact-price"},
            json=payload,
        )
        replay = await client.put(
            f"/v1/operations/offering-versions/{target}/booking-terms",
            headers={"Idempotency-Key": "exact-price"},
            json=payload,
        )
    assert first.status_code == replay.status_code == 200, first.text
    assert first.json() == replay.json()
    assert isinstance(first.json()["amount"], str)
    stored = admin_conn.execute(
        "SELECT amount FROM request_engine.offering_version_booking_terms "
        "WHERE offering_version_id=%s",
        (target,),
    ).fetchall()
    assert stored == [(Decimal(payload["amount"]),)]
    assert Decimal(first.json()["amount"]) == stored[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_amount",
    [
        "99999999999999.111111",
        "1.25",
        "1.0",
        "true",
        '"0E-999999999"',
        '"0E+999999999"',
        '"1.0000001"',
        '"100000000000000"',
    ],
)
@pytest.mark.parametrize("operation", ["catalog", "configure", "supersede"])
async def test_raw_fractional_json_rejected_before_owner_with_no_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    raw_amount: str,
    operation: str,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    before = _facts(admin_conn)
    app = _app(
        ActorContext(world.organization_id, world.principal_id, frozenset({"catalog.manage"})),
        session_factory,
    )
    payload: dict[str, object] = {
        "authority_party_id": str(world.authority_party_id),
        "currency": "DOP",
        "amount": "REPLACE_WITH_RAW_NUMBER",
    }
    if operation == "catalog":
        path = f"/v1/operations/offering-versions/{world.offering_version_id}/booking-terms"
        method = "PUT"
    else:
        payload["effective_from"] = "2026-10-06T00:00:00Z"
        method = "POST"
        if operation == "configure":
            path = "/v1/operations/context-terms"
            payload.update(
                resource_location_assignment_id=str(world.assignment_id),
                offering_version_id=str(world.offering_version_id),
            )
        else:
            path = f"/v1/operations/context-terms/{world.context_terms_id}/supersede"
            payload["expected_current_revision"] = 1
    content = json.dumps(payload).replace('"REPLACE_WITH_RAW_NUMBER"', raw_amount)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.request(
            method,
            path,
            content=content,
            headers={"Content-Type": "application/json", "Idempotency-Key": "raw-money"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"
    assert _facts(admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["99999999999999.111111", 19, "0.0000000", "1.0000000"])
@pytest.mark.parametrize("operation", ["configure", "supersede"])
async def test_booking_lossless_price_persists_exactly_and_replays(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    amount: str | int,
    operation: str,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    app = _app(
        ActorContext(world.organization_id, world.principal_id, frozenset({"catalog.manage"})),
        session_factory,
    )
    payload: dict[str, object] = {
        "authority_party_id": str(world.authority_party_id),
        "currency": "DOP",
        "amount": amount,
        "effective_from": "2026-10-06T00:00:00Z",
    }
    if operation == "configure":
        version = admin_conn.execute(
            "INSERT INTO request_engine.offering_versions"
            "(organization_id,offering_id,version,duration_minutes) "
            "SELECT organization_id,offering_id,2,30 FROM request_engine.offering_versions "
            "WHERE id=%s RETURNING id",
            (world.offering_version_id,),
        ).fetchone()
        assert version is not None
        payload.update(
            resource_location_assignment_id=str(world.assignment_id),
            offering_version_id=str(version[0]),
        )
        path = "/v1/operations/context-terms"
    else:
        payload["expected_current_revision"] = 1
        path = f"/v1/operations/context-terms/{world.context_terms_id}/supersede"
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        first = await client.post(
            path,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "Idempotency-Key": "exact-booking"},
        )
        replay = await client.post(
            path,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "Idempotency-Key": "exact-booking"},
        )
    assert first.status_code == replay.status_code == 200, first.text
    assert first.json() == replay.json()
    assert isinstance(first.json()["amount"], str)
    stored = admin_conn.execute(
        "SELECT amount FROM request_engine.booking_context_terms WHERE id=%s",
        (UUID(first.json()["context_terms_id"]),),
    ).fetchone()
    assert stored == (Decimal(amount),)
    assert Decimal(first.json()["amount"]) == Decimal(amount)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount", ["NaN", "-1", "1.0000001", "100000000000000", "0E-999999999", "0E+999999999"]
)
async def test_booking_owner_and_direct_adapter_reject_inexact_price_without_effect(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    amount: str,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    before = _facts(admin_conn)
    configure = booking_configure.ConfigureBookingContextTermsCommand(
        world.organization_id,
        world.principal_id,
        world.authority_party_id,
        world.assignment_id,
        world.offering_version_id,
        datetime(2026, 10, 6, tzinfo=UTC),
        None,
        Decimal(amount),
        "DOP",
        None,
        True,
        "invalid-booking-price",
    )
    supersede = booking_supersede.SupersedeBookingContextTermsCommand(
        world.organization_id,
        world.principal_id,
        world.authority_party_id,
        world.context_terms_id,
        1,
        datetime(2026, 10, 6, tzinfo=UTC),
        Decimal(amount),
        "DOP",
        None,
        True,
        "invalid-booking-price",
    )
    config_handler = PostgresContextualConfigCommands(session_factory)
    supersede_handler = PostgresContextualTermsSupersessionCommands(session_factory)
    with pytest.raises(BookingTermsInvalidInput):
        await booking_configure.configure_booking_context_terms(config_handler, configure)
    with pytest.raises(BookingTermsInvalidInput):
        await config_handler.configure_booking_context_terms(configure)
    with pytest.raises(BookingTermsInvalidInput):
        await booking_supersede.supersede_booking_context_terms(supersede_handler, supersede)
    with pytest.raises(BookingTermsInvalidInput):
        await supersede_handler.supersede_booking_context_terms(supersede)
    assert _facts(admin_conn) == before
