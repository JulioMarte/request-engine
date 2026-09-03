from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .tenant_sandbox import ALL_PUBLIC_CAPABILITIES, TenantSandbox, auth, first_slot

FRONT_DESK_CAPABILITIES = frozenset(
    {
        "appointments.day_board",
        "queue.check_in",
        "queue.staff_read",
        "queue.recall_hold",
        "queue.release_recall_hold",
    }
)


def front_desk_actor(sandbox: TenantSandbox) -> ActorContext:
    return ActorContext(
        sandbox.organization_id,
        sandbox.principal_id,
        ALL_PUBLIC_CAPABILITIES | FRONT_DESK_CAPABILITIES,
    )


async def book_and_check_in(client: AsyncClient, sandbox: TenantSandbox) -> tuple[dict, dict]:
    slot = await first_slot(client, sandbox)
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    reservation = booked.json()
    checked_in = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id), "reservation_id": reservation["id"]},
        headers=auth(sandbox, idempotency_key=f"check-in-{uuid4().hex}"),
    )
    assert checked_in.status_code == 201, checked_in.text
    return reservation, checked_in.json()


def day_params(sandbox: TenantSandbox) -> dict[str, str]:
    return {
        "window_start": datetime(2030, 1, 7, 0, 0, tzinfo=UTC).isoformat(),
        "window_end": datetime(2030, 1, 8, 0, 0, tzinfo=UTC).isoformat(),
        "location_id": str(sandbox.location_id),
    }
