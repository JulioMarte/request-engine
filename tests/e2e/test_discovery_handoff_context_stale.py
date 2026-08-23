from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import ContextualSupply, contextualize_sandbox
from .discovery_runtime_support import discovery_client
from .discovery_seed_support import create_classification, publish_sandbox, search_body
from .operational_support import PgConnection, RuntimeCredentialsLike
from .tenant_sandbox import TenantSandbox, auth, client_for, seed_tenant_sandbox


def _change_terms(conn: PgConnection, tenant: TenantSandbox, ctx: ContextualSupply) -> None:
    del tenant
    conn.execute(
        "UPDATE request_engine.booking_context_terms SET amount=4100 WHERE id=%s",
        (ctx.context_terms_id,),
    )


def _close_schedule(conn: PgConnection, tenant: TenantSandbox, ctx: ContextualSupply) -> None:
    del ctx
    conn.execute(
        """
        INSERT INTO request_engine.location_hours_exceptions (
            organization_id, location_id, during, exception_kind, reason
        ) VALUES (
            %s, %s,
            tstzrange('2030-01-07T13:00:00+00','2030-01-07T16:00:00+00','[)'),
            'unavailable', 'F2 stale proof'
        )
        """,
        (tenant.organization_id, tenant.location_id),
    )


def _retire_assignment(conn: PgConnection, tenant: TenantSandbox, ctx: ContextualSupply) -> None:
    conn.execute(
        """
        UPDATE request_engine.resource_location_assignments
           SET status='retired',
               effective_during=tstzrange(
                   lower(effective_during),
                   '2030-01-07T12:00:00+00'::timestamptz,
                   '[)'
               )
         WHERE organization_id=%s AND id=%s
        """,
        (tenant.organization_id, ctx.assignment_id),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.adversarial
@pytest.mark.parametrize("mutate", [_change_terms, _close_schedule, _retire_assignment])
async def test_discoopt_becomes_stale_after_material_f1_context_change(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
    mutate: Callable[[PgConnection, TenantSandbox, ContextualSupply], None],
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, f"f2-stale-{uuid4().hex[:6]}")
    context = contextualize_sandbox(e2e_admin_conn, tenant)
    classification_id, key = create_classification(e2e_admin_conn)
    publish_sandbox(e2e_admin_conn, tenant, classification_id, latitude=19.8, longitude=-70.7)
    async with discovery_client(
        e2e_admin_conn, e2e_session_factory, app_runtime_credentials.database_url
    ) as discovery:
        found = await discovery.post("/v1/discovery/supply/search", json=search_body(key))
    assert found.status_code == 200, found.text
    options = cast(list[dict[str, Any]], found.json())
    option_id = cast(str, options[0]["option_id"])

    mutate(e2e_admin_conn, tenant, context)
    async with client_for(e2e_session_factory, tenant) as booking:
        result = await booking.post(
            "/v1/appointments",
            headers=auth(tenant, idempotency_key=f"f2-stale-book-{uuid4().hex}"),
            json={"option_id": option_id, "subject_party_id": str(tenant.party_id)},
        )
    assert result.status_code in {409, 422}, result.text
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.capacity_claims WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone() == (0,)
