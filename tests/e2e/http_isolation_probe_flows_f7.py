from __future__ import annotations

from typing import TYPE_CHECKING

from .http_surface import PROBE_UUID, PublicHttpOperation

if TYPE_CHECKING:
    from .http_isolation_probes import ForeignObjects
    from .tenant_sandbox import TenantSandbox


F7_PROBE_NAMES = frozenset(
    {
        "front_desk.day_board",
        "queue.operator_select",
        "queue.recall_hold",
        "queue.release_recall_hold",
        "queue.skip",
    }
)


def foreign_request(
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    name = operation.name
    if name == "front_desk.day_board":
        return (
            "/v1/front-desk/day-board",
            {
                "window_start": "2030-01-07T12:00:00+00:00",
                "window_end": "2030-01-07T16:00:00+00:00",
            },
            None,
            200,
        )
    if name == "queue.operator_select":
        return (
            f"/v1/queues/{foreign.queue_id}/entries/{objects.queue_entry_id}/operator-select",
            {},
            {"expected_revision": objects.queue_entry_revision, "reason": "operator_override"},
            404,
        )
    if name == "queue.recall_hold":
        return (
            f"/v1/queues/{foreign.queue_id}/entries/{objects.queue_entry_id}/recall-hold",
            {},
            {
                "expected_revision": objects.queue_entry_revision,
                "kind": "until_customer_initiates",
                "release_at": None,
                "reason": "operator_override",
            },
            404,
        )
    if name == "queue.release_recall_hold":
        return (
            f"/v1/queues/{foreign.queue_id}/entries/{objects.queue_entry_id}/recall-hold/release",
            {},
            {"hold_id": PROBE_UUID, "expected_revision": objects.queue_entry_revision},
            404,
        )
    if name == "queue.skip":
        return f"/v1/queues/{foreign.queue_id}/skip", {}, {"reason": "operator_override"}, 404
    raise AssertionError(f"missing F7 tenant probe for {name}")
