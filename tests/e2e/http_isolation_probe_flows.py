from __future__ import annotations

from typing import TYPE_CHECKING

from .http_isolation_probe_flows_s0b import foreign_request as _s0b_request
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
    name = operation.name
    if name == "queue.list":
        return "/v1/queues", {}, None, 200
    if name == "queue.join":
        return (
            f"/v1/queues/{actor.queue_id}/join",
            {},
            {"subject_party_id": str(foreign.party_id), "offering_id": str(actor.offering_id)},
            422,
        )
    if name == "queue.status":
        return (
            f"/v1/queues/{foreign.queue_id}/status",
            {"subject_party_id": str(actor.party_id)},
            None,
            404,
        )
    if name == "queue.leave":
        return (
            f"/v1/queues/{foreign.queue_id}/entries/{objects.queue_entry_id}/leave",
            {},
            {"expected_revision": objects.queue_entry_revision, "reason": "cross tenant"},
            404,
        )
    if name == "queue.call_next":
        return f"/v1/queues/{foreign.queue_id}/call-next", {}, None, 404
    if name == "waitlist.join":
        return (
            "/v1/waitlist",
            {},
            {"offering_id": str(actor.offering_id), "subject_party_id": str(foreign.party_id)},
            422,
        )
    if name == "waitlist.read":
        return f"/v1/waitlist/{objects.waitlist_entry_id}", {}, None, 404
    if name == "waitlist.leave":
        return (
            f"/v1/waitlist/{objects.waitlist_entry_id}/leave",
            {},
            {"expected_revision": objects.waitlist_revision, "reason": "cross tenant"},
            404,
        )
    if name == "requests.submit":
        return (
            f"/v1/requests/definitions/{foreign.request_key}/submit",
            {},
            {"payload": {"message": "cross tenant"}},
            404,
        )
    if name == "requests.read":
        return f"/v1/requests/{objects.request_id}", {}, None, 404
    if name == "requests.cancel":
        return (
            f"/v1/requests/{objects.request_id}/cancel",
            {},
            {"reason": "cross tenant", "expected_revision": objects.request_revision},
            404,
        )
    if name == "reminders.create":
        return (
            "/v1/reminders",
            {},
            {
                "subject_party_id": str(foreign.party_id),
                "purpose": "medication_reminder",
                "timezone": "America/Santo_Domingo",
                "daily_times": ["08:00:00"],
                "channel_policy": {
                    "channels": ["email"],
                    "provider_key": "provider-a",
                },
                "template_key": "medication-reminder",
                "template_version": 1,
            },
            403,
        )
    if name == "reminders.read":
        return f"/v1/reminders/{objects.reminder_plan_id}", {}, None, 404
    if name == "reminders.cancel":
        return (
            f"/v1/reminders/{objects.reminder_plan_id}/cancel",
            {},
            {"expected_revision": objects.reminder_revision, "reason": "cross tenant"},
            404,
        )
    if name.startswith("parties.") or name.startswith("staff."):
        return _s0b_request(operation, actor, foreign, objects)
    raise AssertionError(f"missing tenant probe for {name}")
