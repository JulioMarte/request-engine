"""Proofs for organization channel policies (operations surface).

A missing policy row must stay distinguishable from an intentionally disabled
purpose: absent rows fall back to the hardcoded patient-transactional default,
disabled purposes reject the CREATION of new intents with a typed error while
leaving in-flight tasks untouched, and enabled rows serve as the org default
only for tasks that carry no task-level channel policy. The configuration
command itself is idempotent and optimistic-revision guarded.
"""

from __future__ import annotations

import json
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    prepare_dispatch,
)
from request_engine.modules.communications.adapters.db.organization_channel_policy_commands import (
    PostgresOrganizationChannelPolicyCommands,
)
from request_engine.modules.communications.adapters.db.task_store import (
    CommunicationTaskIntent,
    insert_or_reuse_communication_task,
)
from request_engine.modules.communications.application.commands import (
    set_organization_channel_policy as policy_commands,
)
from request_engine.modules.communications.application.errors import (
    OrganizationChannelPolicyRevisionConflict,
)
from request_engine.modules.communications.domain.delivery_policy import (
    patient_transactional_channel_policy,
)
from request_engine.modules.communications.domain.errors import ChannelPurposeDisabled
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict

pytestmark = pytest.mark.postgres

PgConnection = Connection[Any]

_PROFILE_SCOPE = "operations.manage_profile"


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


class PolicyWorld:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    recipient_party_id: UUID


def _seed_world(
    conn: PgConnection, prefix: str, *, contact_channels: tuple[str, ...]
) -> PolicyWorld:
    world = PolicyWorld()
    suffix = uuid4().hex
    world.organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{suffix}", f"{prefix} {suffix}"),
    )
    world.principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (world.organization_id, f"operator-{suffix}"),
    )
    world.authority_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'organization', %s)
        RETURNING id
        """,
        (world.organization_id, f"Authority {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', %s, clock_timestamp() + interval '1 day')
        """,
        (world.organization_id, world.principal_id, world.authority_party_id, _PROFILE_SCOPE),
    )
    world.recipient_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (world.organization_id, f"Recipient {suffix}"),
    )
    for channel in contact_channels:
        conn.execute(
            """
            INSERT INTO request_engine.party_contact_points (
                organization_id, party_id, channel, normalized_value, verified, active
            ) VALUES (%s, %s, %s, %s, true, true)
            """,
            (world.organization_id, world.recipient_party_id, channel, f"{channel}-{suffix}"),
        )
    return world


def _policy_command(
    world: PolicyWorld,
    *,
    purpose: str,
    enabled: bool,
    expected_revision: int,
    channels: tuple[str, ...] = ("email",),
    key: str | None = None,
) -> policy_commands.SetOrganizationChannelPolicyCommand:
    return policy_commands.SetOrganizationChannelPolicyCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        authority_party_id=world.authority_party_id,
        policy=policy_commands.OrganizationChannelPolicyInput(
            purpose=purpose,
            enabled=enabled,
            channels=channels,
        ),
        expected_revision=expected_revision,
        idempotency_key=key or f"channel-policy-{uuid4().hex}",
    )


def _stored_policy(
    conn: PgConnection, world: PolicyWorld, purpose: str
) -> tuple[bool, int, dict[str, object]] | None:
    row = conn.execute(
        """
        SELECT enabled, revision, channel_policy
        FROM request_engine.organization_channel_policies
        WHERE organization_id = %s AND purpose = %s
        """,
        (world.organization_id, purpose),
    ).fetchone()
    if row is None:
        return None
    return (bool(row[0]), int(row[1]), cast(dict[str, object], row[2]))


def _seed_task(
    conn: PgConnection,
    world: PolicyWorld,
    *,
    purpose: str,
    channel_policy: dict[str, object],
    status: str = "pending",
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, purpose, source_kind,
            channel_policy, template_key, template_version, render_context,
            dedupe_key, status
        ) VALUES (%s, %s, %s, 'Test', %s::jsonb, 'test_template', 1, '{}'::jsonb, %s, %s)
        RETURNING id
        """,
        (
            world.organization_id,
            world.recipient_party_id,
            purpose,
            json.dumps(channel_policy),
            f"dedupe-{uuid4().hex}",
            status,
        ),
    )


@pytest.mark.asyncio
async def test_channel_policy_upsert_is_idempotent_and_revision_guarded(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_world(admin_conn, "org-chanpol", contact_channels=("email",))
    commands = PostgresOrganizationChannelPolicyCommands(command_session_factory)
    purpose = "appointment_confirmation"
    key = f"channel-policy-{uuid4().hex}"

    created = await commands.set_organization_channel_policy(
        _policy_command(world, purpose=purpose, enabled=True, expected_revision=0, key=key)
    )
    assert created.revision == 1
    assert created.enabled is True
    assert created.channel_policy["channels"] == ["email"]
    assert _stored_policy(admin_conn, world, purpose) == (
        True,
        1,
        {"channels": ["email"], "reconcile_after_seconds": 300, "retry_after_seconds": 60},
    )

    replay = await commands.set_organization_channel_policy(
        _policy_command(world, purpose=purpose, enabled=True, expected_revision=0, key=key)
    )
    assert replay == created

    stale = _policy_command(world, purpose=purpose, enabled=False, expected_revision=0)
    with pytest.raises(OrganizationChannelPolicyRevisionConflict) as conflict:
        await commands.set_organization_channel_policy(stale)
    assert (conflict.value.expected, conflict.value.actual) == (0, 1)
    assert _stored_policy(admin_conn, world, purpose) == (
        True,
        1,
        {"channels": ["email"], "reconcile_after_seconds": 300, "retry_after_seconds": 60},
    )

    updated = await commands.set_organization_channel_policy(
        _policy_command(
            world,
            purpose=purpose,
            enabled=False,
            expected_revision=1,
            channels=("whatsapp",),
        )
    )
    assert updated.revision == 2
    assert updated.enabled is False
    stored = _stored_policy(admin_conn, world, purpose)
    assert stored is not None and stored[0] is False and stored[1] == 2

    with pytest.raises(IdempotencyConflict):
        await commands.set_organization_channel_policy(
            _policy_command(
                world,
                purpose=purpose,
                enabled=True,
                expected_revision=2,
                channels=("sms",),
                key=key,
            )
        )


@pytest.mark.asyncio
async def test_disabled_purpose_rejects_new_intents_and_spares_in_flight_tasks(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_world(admin_conn, "org-chanpol-disable", contact_channels=("whatsapp",))
    commands = PostgresOrganizationChannelPolicyCommands(command_session_factory)
    await commands.set_organization_channel_policy(
        _policy_command(
            world,
            purpose="slot_offer_available",
            enabled=False,
            expected_revision=0,
            channels=("whatsapp",),
        )
    )

    intent = CommunicationTaskIntent(
        organization_id=world.organization_id,
        recipient_party_id=world.recipient_party_id,
        contact_point_id=None,
        purpose="slot_offer_available",
        source_kind="SlotOffer",
        source_id=uuid4(),
        channel_policy=patient_transactional_channel_policy(),
        template_key="slot_offer_available",
        template_version=1,
        render_context={},
        dedupe_key=f"slot-offer-{uuid4().hex}:available:v1",
        not_before=None,
        expires_at=None,
    )
    async with tenant_transaction(command_session_factory, world.organization_id) as session:
        with pytest.raises(ChannelPurposeDisabled) as rejected:
            await insert_or_reuse_communication_task(session, intent)
    assert rejected.value.purpose == "slot_offer_available"

    in_flight_id = _seed_task(
        admin_conn,
        world,
        purpose="slot_offer_available",
        channel_policy=patient_transactional_channel_policy(),
    )
    async with tenant_transaction(command_session_factory, world.organization_id) as session:
        work = await prepare_dispatch(
            session,
            organization_id=world.organization_id,
            communication_task_id=in_flight_id,
            configured_provider_keys=("provider-a",),
        )
    assert work.kind is DeliveryWorkKind.SEND
    assert work.send_request is not None
    assert work.send_request.channel == "whatsapp"

    row = admin_conn.execute(
        """
        SELECT status FROM request_engine.communication_tasks
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, in_flight_id),
    ).fetchone()
    assert row is not None and cast(str, row[0]) in {"pending", "delivering"}


@pytest.mark.asyncio
async def test_task_level_policy_beats_org_policy_and_disabled_rows(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_world(
        admin_conn,
        "org-chanpol-tasklevel",
        contact_channels=("whatsapp", "email"),
    )
    commands = PostgresOrganizationChannelPolicyCommands(command_session_factory)
    await commands.set_organization_channel_policy(
        _policy_command(
            world,
            purpose="appointment_confirmation",
            enabled=True,
            expected_revision=0,
            channels=("email",),
        )
    )

    task_id = _seed_task(
        admin_conn,
        world,
        purpose="appointment_confirmation",
        channel_policy={"channels": ["whatsapp"]},
    )
    async with tenant_transaction(command_session_factory, world.organization_id) as session:
        work = await prepare_dispatch(
            session,
            organization_id=world.organization_id,
            communication_task_id=task_id,
            configured_provider_keys=("provider-a",),
        )
    assert work.kind is DeliveryWorkKind.SEND
    assert work.send_request is not None
    assert work.send_request.channel == "whatsapp"


@pytest.mark.asyncio
async def test_org_policy_is_default_for_sentinel_tasks_and_absent_falls_back(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    configured = _seed_world(
        admin_conn,
        "org-chanpol-orgdefault",
        contact_channels=("whatsapp", "email"),
    )
    commands = PostgresOrganizationChannelPolicyCommands(command_session_factory)
    await commands.set_organization_channel_policy(
        _policy_command(
            configured,
            purpose="slot_offer_available",
            enabled=True,
            expected_revision=0,
            channels=("email",),
        )
    )
    configured_task = _seed_task(
        admin_conn,
        configured,
        purpose="slot_offer_available",
        channel_policy=patient_transactional_channel_policy(),
    )
    async with tenant_transaction(command_session_factory, configured.organization_id) as session:
        work = await prepare_dispatch(
            session,
            organization_id=configured.organization_id,
            communication_task_id=configured_task,
            configured_provider_keys=("provider-a",),
        )
    assert work.kind is DeliveryWorkKind.SEND
    assert work.send_request is not None
    assert work.send_request.channel == "email"

    unconfigured = _seed_world(
        admin_conn,
        "org-chanpol-absent",
        contact_channels=("whatsapp", "email"),
    )
    assert _stored_policy(admin_conn, unconfigured, "slot_offer_available") is None
    unconfigured_task = _seed_task(
        admin_conn,
        unconfigured,
        purpose="slot_offer_available",
        channel_policy=patient_transactional_channel_policy(),
    )
    async with tenant_transaction(command_session_factory, unconfigured.organization_id) as session:
        fallback = await prepare_dispatch(
            session,
            organization_id=unconfigured.organization_id,
            communication_task_id=unconfigured_task,
            configured_provider_keys=("provider-a",),
        )
    assert fallback.kind is DeliveryWorkKind.SEND
    assert fallback.send_request is not None
    assert fallback.send_request.channel == "whatsapp"
