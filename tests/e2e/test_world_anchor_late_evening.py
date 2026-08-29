from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import f4_actor, seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import book_commitments
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from .world_clock import TZ, world_window_start

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
]


async def test_late_evening_anchor_keeps_the_world_on_one_local_business_day(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "world-anchor-late-evening")
    sandbox: TenantSandbox = five_minute_sandbox(e2e_admin_conn, base)
    actors = {sandbox.token: f4_actor(sandbox)}

    from . import world_clock as world_clock_module

    real_anchor = world_clock_module.anchor_for

    def forced_late(now: datetime) -> datetime:
        return real_anchor(now + timedelta(hours=23))

    monkeypatch.setattr(world_clock_module, "anchor_for", forced_late)
    anchored_date = world_window_start(e2e_admin_conn).astimezone(TZ).date()
    seed_today_schedule(e2e_admin_conn, sandbox)

    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        reservations, slots = await book_commitments(client, e2e_admin_conn, sandbox)

    assert len(reservations) == 10
    booked_dates = {
        datetime.fromisoformat(cast(str, slot["start_at"])).astimezone(TZ).date()
        for slot in slots[:11]
    }
    assert booked_dates == {anchored_date}
