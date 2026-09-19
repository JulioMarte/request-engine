"""E3 resource-effective authority inspection through the owner-backed inspector.

The inspector must agree with the real owner authorization for the same revision,
never answer allowed for a foreign/absent target, and never mutate authority,
idempotency, audit or outbox state. PostgreSQL is the execution boundary.
"""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import provision_root
from psycopg import Connection

from request_engine.modules.booking.adapters.db.resource_authority_inspector import (
    PostgresResourceAuthorityInspector,
)
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import (
    BOOK_APPOINTMENT_SCOPE,
    SUBJECT_OVERRIDE_PERMISSION,
)
from request_engine.modules.booking.application.errors import SubjectAuthorityRequired
from request_engine.modules.tenancy.contracts.resource_authority import (
    ResourceAuthorityDecisionKind,
    ResourceAuthorityOperation,
    ResourceAuthorityQuery,
    ResourceAuthorityTargetNotFound,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    OperationalAuthorityRequired,
    require_operational_authority,
)

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]

_INSPECT_CAPABILITY = "authority.inspect_resource"


def _create_party(conn: Connection[Any], *, organization_id: UUID) -> UUID:
    party_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.parties (id, organization_id, party_kind, display_name) "
        "VALUES (%s, %s, 'person', %s)",
        (party_id, organization_id, f"Authority Target {party_id.hex[:8]}"),
    )
    return party_id


def _grant_representation(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    scope_key: str,
) -> UUID:
    representation_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.representations ("
        "id, organization_id, principal_id, represented_party_id, authority_kind, scope_key, "
        "valid_from) VALUES (%s, %s, %s, %s, 'delegated', %s, clock_timestamp())",
        (representation_id, organization_id, principal_id, party_id, scope_key),
    )
    return representation_id


def _representation_revision(conn: Connection[Any], representation_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.representations WHERE id = %s",
        (representation_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _state_fingerprint(
    conn: Connection[Any], *, organization_id: UUID, principal_id: UUID
) -> tuple[object, ...]:
    return (
        conn.execute(
            "SELECT count(*), md5(COALESCE(string_agg(id::text || ':' || revision::text, ',' "
            "ORDER BY id), '')) FROM request_engine.representations "
            "WHERE organization_id = %s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*), md5(COALESCE(string_agg(id::text || ':' || revision::text, ',' "
            "ORDER BY id), '')) FROM request_engine.principal_authority_grants "
            "WHERE organization_id = %s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
            (principal_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.audit_records WHERE organization_id = %s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id = %s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.idempotency_records WHERE organization_id = %s",
            (organization_id,),
        ).fetchone(),
    )


async def _owner_book_allows(
    session_factory: SessionFactory,
    *,
    actor: ActorContext,
    subject_party_id: UUID,
) -> bool:
    """Independent oracle: the real booking subject-authority primitive."""

    async with actor_transaction(session_factory, actor) as session:
        try:
            await require_subject_authority(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                subject_party_id=subject_party_id,
                scope_key=BOOK_APPOINTMENT_SCOPE,
                allow_operator_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            )
        except SubjectAuthorityRequired:
            return False
    return True


async def _owner_supply_allows(
    session_factory: SessionFactory,
    *,
    actor: ActorContext,
    authority_party_id: UUID,
) -> bool:
    """Independent oracle: the real booking operational-authority primitive."""

    async with actor_transaction(session_factory, actor) as session:
        try:
            await require_operational_authority(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                authority_party_id=authority_party_id,
                scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            )
        except OperationalAuthorityRequired:
            return False
    return True


@pytest.mark.asyncio
async def test_inspection_agrees_with_owner_authorization_for_book(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    subject = _create_party(admin_conn, organization_id=org)
    representation_id = _grant_representation(
        admin_conn,
        organization_id=org,
        principal_id=controller,
        party_id=subject,
        scope_key=BOOK_APPOINTMENT_SCOPE,
    )
    actor = ActorContext(org, controller, frozenset({_INSPECT_CAPABILITY}))
    inspector = PostgresResourceAuthorityInspector(command_session_factory)

    allowed = await inspector.inspect(
        actor,
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
        ),
    )
    assert allowed.decision is ResourceAuthorityDecisionKind.ALLOWED
    assert allowed.reason_codes == ("current_representation",)
    assert allowed.representation_revision == _representation_revision(
        admin_conn, representation_id
    )
    assert await _owner_book_allows(command_session_factory, actor=actor, subject_party_id=subject)

    admin_conn.execute(
        "UPDATE request_engine.representations SET status='revoked', revision=revision+1 "
        "WHERE id=%s",
        (representation_id,),
    )
    denied = await inspector.inspect(
        actor,
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
        ),
    )
    assert denied.decision is ResourceAuthorityDecisionKind.DENIED
    assert denied.reason_codes == ("no_current_representation",)
    assert denied.representation_revision is None
    assert not await _owner_book_allows(
        command_session_factory, actor=actor, subject_party_id=subject
    )


@pytest.mark.asyncio
async def test_inspection_override_requires_a_visible_target(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    subject = _create_party(admin_conn, organization_id=org)
    actor = ActorContext(
        org, controller, frozenset({_INSPECT_CAPABILITY, SUBJECT_OVERRIDE_PERMISSION})
    )
    inspector = PostgresResourceAuthorityInspector(command_session_factory)

    overridden = await inspector.inspect(
        actor,
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
        ),
    )
    assert overridden.decision is ResourceAuthorityDecisionKind.ALLOWED
    assert overridden.reason_codes == ("operator_override",)
    assert overridden.representation_revision is None
    assert await _owner_book_allows(command_session_factory, actor=actor, subject_party_id=subject)

    # An override never manufactures authority over an absent target.
    with pytest.raises(ResourceAuthorityTargetNotFound):
        await inspector.inspect(
            actor,
            ResourceAuthorityQuery(
                operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK,
                subject_party_id=uuid4(),
            ),
        )


@pytest.mark.asyncio
async def test_inspection_agrees_with_owner_authorization_for_supply(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    supply_party = _create_party(admin_conn, organization_id=org)
    representation_id = _grant_representation(
        admin_conn,
        organization_id=org,
        principal_id=controller,
        party_id=supply_party,
        scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    )
    actor = ActorContext(org, controller, frozenset({_INSPECT_CAPABILITY}))
    inspector = PostgresResourceAuthorityInspector(command_session_factory)
    query = ResourceAuthorityQuery(
        operation=ResourceAuthorityOperation.BOOKING_MANAGE_SUPPLY,
        authority_party_id=supply_party,
    )

    allowed = await inspector.inspect(actor, query)
    assert allowed.decision is ResourceAuthorityDecisionKind.ALLOWED
    assert allowed.representation_revision == _representation_revision(
        admin_conn, representation_id
    )
    assert await _owner_supply_allows(
        command_session_factory, actor=actor, authority_party_id=supply_party
    )

    admin_conn.execute(
        "UPDATE request_engine.representations SET status='revoked', revision=revision+1 "
        "WHERE id=%s",
        (representation_id,),
    )
    denied = await inspector.inspect(actor, query)
    assert denied.decision is ResourceAuthorityDecisionKind.DENIED
    assert not await _owner_supply_allows(
        command_session_factory, actor=actor, authority_party_id=supply_party
    )


@pytest.mark.asyncio
async def test_inspection_treats_foreign_and_random_targets_indistinguishably(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    foreign_org, _fparty, _fcontroller, _ = provision_root(admin_conn)
    foreign_party = _create_party(admin_conn, organization_id=foreign_org)
    actor = ActorContext(org, controller, frozenset({_INSPECT_CAPABILITY}))
    inspector = PostgresResourceAuthorityInspector(command_session_factory)

    with pytest.raises(ResourceAuthorityTargetNotFound) as foreign:
        await inspector.inspect(
            actor,
            ResourceAuthorityQuery(
                operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK,
                subject_party_id=foreign_party,
            ),
        )
    with pytest.raises(ResourceAuthorityTargetNotFound) as random:
        await inspector.inspect(
            actor,
            ResourceAuthorityQuery(
                operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK,
                subject_party_id=uuid4(),
            ),
        )
    assert type(foreign.value) is type(random.value)
    with pytest.raises(ResourceAuthorityTargetNotFound):
        await inspector.inspect(
            actor,
            ResourceAuthorityQuery(
                operation=ResourceAuthorityOperation.BOOKING_MANAGE_SUPPLY,
                authority_party_id=foreign_party,
            ),
        )


@pytest.mark.asyncio
async def test_inspection_is_mutation_free(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    subject = _create_party(admin_conn, organization_id=org)
    _grant_representation(
        admin_conn,
        organization_id=org,
        principal_id=controller,
        party_id=subject,
        scope_key=BOOK_APPOINTMENT_SCOPE,
    )
    actor = ActorContext(org, controller, frozenset({_INSPECT_CAPABILITY}))
    inspector = PostgresResourceAuthorityInspector(command_session_factory)
    before = _state_fingerprint(admin_conn, organization_id=org, principal_id=controller)
    for _ in range(3):
        await inspector.inspect(
            actor,
            ResourceAuthorityQuery(
                operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
            ),
        )
    assert _state_fingerprint(admin_conn, organization_id=org, principal_id=controller) == before


@pytest.mark.asyncio
async def test_inspection_is_indeterminate_when_actor_authority_is_not_visible(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    subject = _create_party(admin_conn, organization_id=org)
    _grant_representation(
        admin_conn,
        organization_id=org,
        principal_id=controller,
        party_id=subject,
        scope_key=BOOK_APPOINTMENT_SCOPE,
    )
    actor = ActorContext(org, controller, frozenset({_INSPECT_CAPABILITY}))
    inspector = PostgresResourceAuthorityInspector(command_session_factory)

    admin_conn.execute(
        "UPDATE request_engine.principals SET active=false WHERE id=%s", (controller,)
    )
    decision = await inspector.inspect(
        actor,
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
        ),
    )
    assert decision.decision is ResourceAuthorityDecisionKind.INDETERMINATE
    assert decision.reason_codes == ("actor_authority_unavailable",)
    assert decision.representation_revision is None

    # A foreign actor tenant is equally indeterminate, never a cross-tenant allow.
    foreign_org, _fparty, _fcontroller, _ = provision_root(admin_conn)
    other = await inspector.inspect(
        replace(actor, organization_id=foreign_org),
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK, subject_party_id=subject
        ),
    )
    assert other.decision is ResourceAuthorityDecisionKind.INDETERMINATE


def test_resource_authority_query_validates_operation_shape() -> None:
    with pytest.raises(ValueError):
        ResourceAuthorityQuery(operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK)
    with pytest.raises(ValueError):
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.APPOINTMENTS_BOOK,
            subject_party_id=uuid4(),
            authority_party_id=uuid4(),
        )
    with pytest.raises(ValueError):
        ResourceAuthorityQuery(operation=ResourceAuthorityOperation.BOOKING_MANAGE_SUPPLY)
    with pytest.raises(ValueError):
        ResourceAuthorityQuery(
            operation=ResourceAuthorityOperation.BOOKING_MANAGE_SUPPLY,
            authority_party_id=uuid4(),
            subject_party_id=uuid4(),
        )
