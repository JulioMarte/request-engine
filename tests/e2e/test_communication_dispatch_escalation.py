"""E2E: S3 escalation replaces the durable poison for reachable recipients.

A recipient with no usable contact point on ANY policy channel still ends in
the durable ``delivery_configuration_invalid`` poison (see
``test_communication_dispatch_configuration_poison``); a recipient reachable
on an earlier policy channel now escalates instead of poisoning.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from . import communication_reconcile_support as reconcile
from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

POLICY = '{"channels": ["whatsapp", "sms"], "provider_key": "provider-a"}'


def _contact_point(
    conn: support.PgConnection,
    organization_id: UUID,
    party_id: UUID,
    channel: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, %s, %s, true) RETURNING id
        """,
        (organization_id, party_id, channel, f"{channel}-{uuid4().hex[:8]}@example.test"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _new_task(conn: support.PgConnection, organization_id: UUID, party_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, purpose, template_key,
            template_version, render_context, channel_policy, dedupe_key,
            status, expires_at
        ) VALUES (%s, %s, 'confirmation', 'booking-confirmed', 1, '{}'::jsonb,
                  %s::jsonb, %s, 'pending', %s)
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            POLICY,
            f"escalate-task:{uuid4().hex}",
            datetime.now(UTC) + timedelta(hours=1),
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
async def test_definitive_failure_escalates_to_next_channel_instead_of_poison(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "escalate-dispatch")
    party_id = support.new_party(e2e_admin_conn, organization_id, "Reachable recipient")
    whatsapp_id = _contact_point(e2e_admin_conn, organization_id, party_id, "whatsapp")
    sms_id = _contact_point(e2e_admin_conn, organization_id, party_id, "phone")
    task_id = _new_task(e2e_admin_conn, organization_id, party_id)

    async with tenant_transaction(e2e_session_factory, organization_id) as session:
        first = await prepare_dispatch(
            session, organization_id=organization_id, communication_task_id=task_id
        )
    assert first.kind is DeliveryWorkKind.SEND
    assert first.send_request is not None
    assert first.send_request.channel == "whatsapp"
    assert first.send_request.contact_point_id == whatsapp_id

    async with tenant_transaction(e2e_session_factory, organization_id) as session:
        finalized = await finalize_provider_result(
            session,
            organization_id=organization_id,
            delivery_id=cast(UUID, first.delivery_id),
            result=ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=False,
                result_data={"source": "escalation-dispatch-test"},
            ),
        )
    assert finalized.task_terminal

    children = e2e_admin_conn.execute(
        """
        SELECT id, contact_point_id, status FROM request_engine.communication_tasks
        WHERE organization_id = %s AND parent_task_id = %s
        """,
        (organization_id, task_id),
    ).fetchall()
    assert len(children) == 1
    child_id, child_contact, child_status = children[0]
    assert (child_contact, child_status) == (sms_id, "pending")

    async with tenant_transaction(e2e_session_factory, organization_id) as session:
        retry = await prepare_dispatch(
            session, organization_id=organization_id, communication_task_id=child_id
        )
    assert retry.kind is DeliveryWorkKind.SEND
    assert retry.send_request is not None
    assert retry.send_request.channel == "sms"
    assert retry.send_request.contact_point_id == sms_id

    escalated = reconcile.outbox_payloads(
        e2e_admin_conn, organization_id, "communication.task_escalated.v1"
    )
    assert len(escalated) == 1
    assert (escalated[0]["from_channel"], escalated[0]["to_channel"]) == ("whatsapp", "sms")
    failures = reconcile.outbox_payloads(
        e2e_admin_conn, organization_id, "communication.task_failed.v1"
    )
    assert [failure["reason"] for failure in failures] == ["provider_non_retryable_failure"]
