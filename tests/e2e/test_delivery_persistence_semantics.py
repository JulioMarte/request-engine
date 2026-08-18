from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


def _new_task(
    conn: support.PgConnection,
    organization_id: UUID,
    party_id: UUID,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, purpose,
            template_key, template_version, dedupe_key
        ) VALUES (%s, %s, 'confirmation', 'booking-confirmed', 1, %s)
        RETURNING id
        """,
        (organization_id, party_id, f"task:{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def test_communication_task_dedupe_is_tenant_scoped_and_contact_fk_is_tenant_safe(
    e2e_admin_conn: support.PgConnection,
) -> None:
    org_a = support.new_org(e2e_admin_conn, "communication-a")
    org_b = support.new_org(e2e_admin_conn, "communication-b")
    party_a = support.new_party(e2e_admin_conn, org_a, "Recipient A")
    party_b = support.new_party(e2e_admin_conn, org_b, "Recipient B")
    contact_a = support.new_contact_point(e2e_admin_conn, org_a, party_a, "a")
    contact_b = support.new_contact_point(e2e_admin_conn, org_b, party_b, "b")
    dedupe = f"appointment-reminder:{uuid4().hex}"

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, dedupe_key
        ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
        """,
        (org_a, party_a, contact_a, dedupe),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_tasks (
                organization_id, recipient_party_id, contact_point_id, purpose,
                template_key, template_version, dedupe_key
            ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
            """,
            (org_a, party_a, contact_a, dedupe),
        )

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, dedupe_key
        ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
        """,
        (org_b, party_b, contact_b, dedupe),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_tasks (
                organization_id, recipient_party_id, contact_point_id, purpose,
                template_key, template_version, dedupe_key
            ) VALUES (%s, %s, %s, 'reminder', 'appointment-reminder', 1, %s)
            """,
            (org_a, party_a, contact_b, f"cross-tenant:{uuid4().hex}"),
        )


def test_communication_delivery_attempt_number_is_unique_per_task(
    e2e_admin_conn: support.PgConnection,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-attempt")
    party_id = support.new_party(e2e_admin_conn, organization_id, "Recipient")
    task_id = _new_task(e2e_admin_conn, organization_id, party_id)

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, status
        ) VALUES (%s, %s, 1, 'email', 'provider-a', %s, 'attempting')
        """,
        (organization_id, task_id, f"send:{uuid4().hex}"),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, status
            ) VALUES (%s, %s, 1, 'email', 'provider-b', %s, 'attempting')
            """,
            (organization_id, task_id, f"send:{uuid4().hex}"),
        )


def test_delivery_provider_idempotency_and_message_id_are_unique_per_tenant_provider(
    e2e_admin_conn: support.PgConnection,
) -> None:
    org_a = support.new_org(e2e_admin_conn, "delivery-dedupe-a")
    org_b = support.new_org(e2e_admin_conn, "delivery-dedupe-b")
    party_a = support.new_party(e2e_admin_conn, org_a, "Recipient A")
    party_b = support.new_party(e2e_admin_conn, org_b, "Recipient B")
    task_a1 = _new_task(e2e_admin_conn, org_a, party_a)
    task_a2 = _new_task(e2e_admin_conn, org_a, party_a)
    task_b = _new_task(e2e_admin_conn, org_b, party_b)
    provider_key = "provider-a"
    idempotency_key = f"send:{uuid4().hex}"
    message_id = f"msg-{uuid4().hex}"

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, provider_message_id, status
        ) VALUES (%s, %s, 1, 'whatsapp', %s, %s, %s, 'accepted')
        """,
        (org_a, task_a1, provider_key, idempotency_key, message_id),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, status
            ) VALUES (%s, %s, 1, 'whatsapp', %s, %s, 'accepted')
            """,
            (org_a, task_a2, provider_key, idempotency_key),
        )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, provider_message_id, status
            ) VALUES (%s, %s, 1, 'whatsapp', %s, %s, %s, 'accepted')
            """,
            (
                org_a,
                task_a2,
                provider_key,
                f"send:{uuid4().hex}",
                message_id,
            ),
        )

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, provider_message_id, status
        ) VALUES (%s, %s, 1, 'whatsapp', %s, %s, %s, 'accepted')
        """,
        (org_b, task_b, provider_key, idempotency_key, message_id),
    )


def test_delivery_attempt_number_must_be_positive(
    e2e_admin_conn: support.PgConnection,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-attempt-check")
    party_id = support.new_party(e2e_admin_conn, organization_id, "Recipient")
    task_id = _new_task(e2e_admin_conn, organization_id, party_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.communication_deliveries (
                organization_id, communication_task_id, attempt_no, channel,
                provider_key, provider_idempotency_key, status
            ) VALUES (%s, %s, 0, 'sms', 'provider-a', %s, 'attempting')
            """,
            (organization_id, task_id, f"send:{uuid4().hex}"),
        )


def test_provider_event_deduplication_scopes_connection_and_tenant(
    e2e_admin_conn: support.PgConnection,
) -> None:
    org_a = support.new_org(e2e_admin_conn, "provider-event-a")
    org_b = support.new_org(e2e_admin_conn, "provider-event-b")
    event_id = f"evt-{uuid4().hex}"

    def insert_event(org: UUID, connection: str, payload_hash: str) -> None:
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.provider_events (
                organization_id, provider_key, connection_key,
                provider_event_id, payload_hash, payload
            ) VALUES (%s, 'provider-a', %s, %s, %s, '{}'::jsonb)
            """,
            (org, connection, event_id, payload_hash),
        )

    insert_event(org_a, "primary", uuid4().hex)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_event(org_a, "primary", uuid4().hex)

    insert_event(org_a, "secondary", uuid4().hex)
    insert_event(org_b, "primary", uuid4().hex)


def test_provider_events_accept_out_of_order_distinct_ids_without_collapsing_history(
    e2e_admin_conn: support.PgConnection,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "provider-out-of-order")
    first_id = f"evt-001-{uuid4().hex}"
    second_id = f"evt-002-{uuid4().hex}"

    for event_id in (second_id, first_id):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.provider_events (
                organization_id, provider_key, connection_key,
                provider_event_id, payload_hash, payload
            ) VALUES (%s, 'provider-a', 'primary', %s, %s, %s::jsonb)
            """,
            (
                organization_id,
                event_id,
                uuid4().hex,
                '{"kind":"delivery_status"}',
            ),
        )

    stored = e2e_admin_conn.execute(
        """
        SELECT provider_event_id
        FROM request_engine.provider_events
        WHERE organization_id = %s
          AND connection_key = 'primary'
          AND provider_event_id IN (%s, %s)
        ORDER BY provider_event_id
        """,
        (organization_id, first_id, second_id),
    ).fetchall()
    assert [row[0] for row in stored] == [first_id, second_id]


def test_reminder_acknowledgement_is_idempotent_per_occurrence_and_subject(
    e2e_admin_conn: support.PgConnection,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "reminder-ack")
    party_id = support.new_party(e2e_admin_conn, organization_id, "Patient")
    plan_row = e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.reminder_plans (
            organization_id, subject_party_id, purpose, timezone,
            schedule_spec, template_key, template_version
        ) VALUES (
            %s, %s, 'medication', 'America/Santo_Domingo',
            '{"type":"daily_times","version":1,"times":["08:00"]}'::jsonb,
            'medication-reminder', 1
        )
        RETURNING id
        """,
        (organization_id, party_id),
    ).fetchone()
    assert plan_row is not None
    plan_id = cast(UUID, plan_row[0])
    occurrence = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.reminder_acknowledgements (
            organization_id, reminder_plan_id, occurrence_at,
            subject_party_id, source_key, reported_value
        ) VALUES (%s, %s, %s, %s, 'patient_reply', 'taken')
        """,
        (organization_id, plan_id, occurrence, party_id),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.reminder_acknowledgements (
                organization_id, reminder_plan_id, occurrence_at,
                subject_party_id, source_key, reported_value
            ) VALUES (%s, %s, %s, %s, 'duplicate_webhook', 'taken')
            """,
            (organization_id, plan_id, occurrence, party_id),
        )


def test_reminder_plan_rejects_unknown_schedule_type(
    e2e_admin_conn: support.PgConnection,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "reminder-schedule-check")
    party_id = support.new_party(e2e_admin_conn, organization_id, "Patient")

    with pytest.raises(psycopg.errors.CheckViolation):
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.reminder_plans (
                organization_id, subject_party_id, purpose, timezone,
                schedule_spec, template_key, template_version
            ) VALUES (
                %s, %s, 'medication', 'America/Santo_Domingo',
                '{"type":"cron","version":1,"expression":"* * * * *"}'::jsonb,
                'medication-reminder', 1
            )
            """,
            (organization_id, party_id),
        )
