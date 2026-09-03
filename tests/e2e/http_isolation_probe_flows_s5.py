from __future__ import annotations

from typing import TYPE_CHECKING

from .http_surface import PublicHttpOperation

if TYPE_CHECKING:
    from .http_isolation_probes import ForeignObjects
    from .tenant_sandbox import TenantSandbox


def foreign_request(
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    del actor, foreign
    if operation.name == "queue.operator_select":
        return (
            f"/v1/queue-entries/{objects.queue_entry_id}/operator-select",
            {},
            {"reason": "urgent", "expected_revision": objects.queue_entry_revision},
            404,
        )
    if operation.name == "queue.recall_hold":
        return (
            f"/v1/queue-entries/{objects.queue_entry_id}/recall-hold",
            {},
            {
                "condition_kind": "until_customer_initiates",
                "expected_revision": objects.queue_entry_revision,
                "reason": "cross tenant",
            },
            404,
        )
    if operation.name == "queue.skip":
        return (
            f"/v1/queue-entries/{objects.queue_entry_id}/skip",
            {},
            {"reason": "no_response", "expected_revision": objects.queue_entry_revision},
            404,
        )
    if operation.name == "queue.release_recall_hold":
        return (
            f"/v1/queue-entries/{objects.queue_entry_id}/recall-hold/release",
            {},
            {
                "hold_id": str(objects.queue_entry_id),
                "expected_revision": objects.queue_entry_revision,
            },
            404,
        )
    raise AssertionError(f"unsupported S5 isolation probe for {operation.name}")
