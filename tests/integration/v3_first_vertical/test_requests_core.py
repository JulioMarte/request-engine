import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.adapters.db.request_reader import PostgresRequestReader
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
    cancel_request,
)
from request_engine.modules.requests.application.commands.complete_request import (
    CompleteRequestCommand,
    complete_request,
)
from request_engine.modules.requests.application.commands.create_request import (
    CreateRequestCommand,
    create_request,
)
from request_engine.modules.requests.application.commands.record_request_result import (
    RecordRequestResultCommand,
    record_request_result,
)
from request_engine.modules.requests.application.errors import (
    ExternalCorrelationConflict,
    RequestDefinitionInactive,
    RequestNotOpen,
    RequestPartyNotUsable,
    RequestPayloadInvalid,
    RequestResultNotDefined,
    RequestResultRequired,
    RequestRevisionConflict,
)
from request_engine.modules.requests.application.queries.get_request_status import (
    get_request_status,
)
from request_engine.modules.requests.contracts.request import (
    ExternalCorrelationInput,
    Request,
    RequestParticipantInput,
    RequestStatus,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class RequestFixture:
    organization_id: UUID
    principal_id: UUID
    requester_party_id: UUID
    recipient_party_id: UUID
    participant_party_id: UUID
    version_with_result_id: UUID
    version_without_result_id: UUID
    inactive_version_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_definition_version(
    conn: PgConnection,
    *,
    organization_id: UUID,
    key: str,
    active: bool,
    input_schema: dict[str, object],
    result_schema: dict[str, object] | None,
) -> UUID:
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (organization_id, key, key.replace("_", " ").title(), active),
    )
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id,
            request_definition_id,
            version,
            input_schema,
            result_schema
        ) VALUES (%s, %s, 1, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            definition_id,
            json.dumps(input_schema),
            json.dumps(result_schema) if result_schema is not None else None,
        ),
    )


def _create_fixture(conn: PgConnection) -> RequestFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"requests-{suffix}", f"Requests Practice {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )

    def create_party(label: str) -> UUID:
        return _uuid_row(
            conn,
            """
            INSERT INTO request_engine.parties (
                organization_id, party_kind, display_name
            ) VALUES (%s, 'person', %s)
            RETURNING id
            """,
            (organization_id, f"{label} {suffix}"),
        )

    requester_party_id = create_party("Requester")
    recipient_party_id = create_party("Recipient")
    participant_party_id = create_party("Authorized contact")

    input_schema: dict[str, object] = {
        "type": "object",
        "required": ["message"],
        "additionalProperties": False,
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    }
    result_schema: dict[str, object] = {
        "type": "object",
        "required": ["quote_total"],
        "additionalProperties": False,
        "properties": {
            "quote_total": {"type": "number", "minimum": 0},
        },
    }

    return RequestFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        requester_party_id=requester_party_id,
        recipient_party_id=recipient_party_id,
        participant_party_id=participant_party_id,
        version_with_result_id=_create_definition_version(
            conn,
            organization_id=organization_id,
            key=f"request_quote_{suffix}",
            active=True,
            input_schema=input_schema,
            result_schema=result_schema,
        ),
        version_without_result_id=_create_definition_version(
            conn,
            organization_id=organization_id,
            key=f"request_callback_{suffix}",
            active=True,
            input_schema=input_schema,
            result_schema=None,
        ),
        inactive_version_id=_create_definition_version(
            conn,
            organization_id=organization_id,
            key=f"inactive_request_{suffix}",
            active=False,
            input_schema=input_schema,
            result_schema=None,
        ),
    )


def _base_create_command(
    fixture: RequestFixture,
    *,
    version_id: UUID,
    message: str,
    idempotency_key: str,
    correlations: tuple[ExternalCorrelationInput, ...] = (),
) -> CreateRequestCommand:
    return CreateRequestCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        request_definition_version_id=version_id,
        requester_party_id=fixture.requester_party_id,
        recipient_party_id=fixture.recipient_party_id,
        payload={"message": message},
        participants=(
            RequestParticipantInput(
                party_id=fixture.participant_party_id,
                role_key="authorized_contact",
            ),
        ),
        correlations=correlations,
        idempotency_key=idempotency_key,
    )


async def _capture(awaitable: Awaitable[Request]) -> Request | Exception:
    try:
        return await awaitable
    except Exception as exc:
        return exc


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_result_completion_and_replay_are_transactional(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)
    reader = PostgresRequestReader(session_factory)
    correlation = ExternalCorrelationInput(
        correlation_kind="conversation",
        provider_key="whatsapp",
        external_key=f"thread-{uuid4().hex}",
    )
    create_command = _base_create_command(
        fixture,
        version_id=fixture.version_with_result_id,
        message="Please prepare a quote",
        idempotency_key=f"request-create-{uuid4().hex}",
        correlations=(correlation,),
    )

    created = await create_request(commands, create_command)
    replay = await create_request(commands, create_command)
    assert replay == created
    assert created.status is RequestStatus.OPEN
    assert created.revision == 1
    assert len(created.participants) == 1
    assert len(created.correlations) == 1

    queried = await get_request_status(
        reader,
        organization_id=fixture.organization_id,
        request_id=created.id,
    )
    assert queried == created

    with pytest.raises(RequestPayloadInvalid):
        await record_request_result(
            commands,
            RecordRequestResultCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_id=created.id,
                result_payload={"quote_total": -1},
                expected_revision=1,
                idempotency_key=f"invalid-result-{uuid4().hex}",
            ),
        )

    result_command = RecordRequestResultCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        request_id=created.id,
        result_payload={"quote_total": 125.5},
        expected_revision=1,
        idempotency_key=f"result-{uuid4().hex}",
    )
    with_result = await record_request_result(commands, result_command)
    result_replay = await record_request_result(commands, result_command)
    assert result_replay == with_result
    assert with_result.status is RequestStatus.OPEN
    assert with_result.result_payload == {"quote_total": 125.5}
    assert with_result.revision == 2

    complete_command = CompleteRequestCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        request_id=created.id,
        expected_revision=2,
        idempotency_key=f"complete-{uuid4().hex}",
    )
    completed = await complete_request(commands, complete_command)
    completed_replay = await complete_request(commands, complete_command)
    assert completed_replay == completed
    assert completed.status is RequestStatus.COMPLETED
    assert completed.revision == 3
    assert completed.completed_at is not None

    with pytest.raises(RequestNotOpen):
        await cancel_request(
            commands,
            CancelRequestCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_id=created.id,
                reason="too late",
                expected_revision=3,
                idempotency_key=f"late-cancel-{uuid4().hex}",
            ),
        )

    event_counts = dict(
        admin_conn.execute(
            """
            SELECT event_type, count(*)
            FROM request_engine.outbox_messages
            WHERE organization_id = %s
              AND aggregate_kind = 'Request'
              AND aggregate_id = %s
            GROUP BY event_type
            """,
            (fixture.organization_id, created.id),
        ).fetchall()
    )
    assert event_counts == {
        "request.completed.v1": 1,
        "request.created.v1": 1,
        "request.result_recorded.v1": 1,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_contract_failures_do_not_mutate_authoritative_state(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)
    reader = PostgresRequestReader(session_factory)

    invalid_create = CreateRequestCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        request_definition_version_id=fixture.version_with_result_id,
        requester_party_id=fixture.requester_party_id,
        payload={"message": ""},
        idempotency_key=f"invalid-create-{uuid4().hex}",
    )
    with pytest.raises(RequestPayloadInvalid):
        await create_request(commands, invalid_create)

    with pytest.raises(RequestDefinitionInactive):
        await create_request(
            commands,
            _base_create_command(
                fixture,
                version_id=fixture.inactive_version_id,
                message="Should not be accepted",
                idempotency_key=f"inactive-{uuid4().hex}",
            ),
        )

    other_organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"other-{uuid4().hex}", "Other tenant"),
    )
    foreign_party_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', 'Foreign party')
        RETURNING id
        """,
        (other_organization_id,),
    )
    with pytest.raises(RequestPartyNotUsable):
        await create_request(
            commands,
            CreateRequestCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_definition_version_id=fixture.version_without_result_id,
                requester_party_id=foreign_party_id,
                payload={"message": "Cross tenant"},
                idempotency_key=f"cross-tenant-{uuid4().hex}",
            ),
        )

    result_required = await create_request(
        commands,
        _base_create_command(
            fixture,
            version_id=fixture.version_with_result_id,
            message="Requires result",
            idempotency_key=f"requires-result-{uuid4().hex}",
        ),
    )
    with pytest.raises(RequestResultRequired):
        await complete_request(
            commands,
            CompleteRequestCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_id=result_required.id,
                expected_revision=1,
                idempotency_key=f"missing-result-{uuid4().hex}",
            ),
        )
    unchanged = await get_request_status(
        reader,
        organization_id=fixture.organization_id,
        request_id=result_required.id,
    )
    assert unchanged is not None
    assert unchanged.status is RequestStatus.OPEN
    assert unchanged.revision == 1

    no_result = await create_request(
        commands,
        _base_create_command(
            fixture,
            version_id=fixture.version_without_result_id,
            message="Callback request",
            idempotency_key=f"no-result-{uuid4().hex}",
        ),
    )
    with pytest.raises(RequestResultNotDefined):
        await record_request_result(
            commands,
            RecordRequestResultCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_id=no_result.id,
                result_payload={"quote_total": 10},
                expected_revision=1,
                idempotency_key=f"unexpected-result-{uuid4().hex}",
            ),
        )
    with pytest.raises(RequestRevisionConflict):
        await cancel_request(
            commands,
            CancelRequestCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                request_id=no_result.id,
                expected_revision=99,
                idempotency_key=f"bad-revision-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_external_correlation_serializes_concurrent_request_creation(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)
    correlation = ExternalCorrelationInput(
        correlation_kind="form_submission",
        provider_key="website",
        external_key=f"submission-{uuid4().hex}",
    )

    first_command = _base_create_command(
        fixture,
        version_id=fixture.version_without_result_id,
        message="First payload",
        idempotency_key=f"race-a-{uuid4().hex}",
        correlations=(correlation,),
    )
    second_command = _base_create_command(
        fixture,
        version_id=fixture.version_without_result_id,
        message="Second payload",
        idempotency_key=f"race-b-{uuid4().hex}",
        correlations=(correlation,),
    )

    first, second = await asyncio.gather(
        _capture(create_request(commands, first_command)),
        _capture(create_request(commands, second_command)),
    )
    outcomes = (first, second)
    assert sum(isinstance(item, Request) for item in outcomes) == 1
    assert sum(isinstance(item, ExternalCorrelationConflict) for item in outcomes) == 1

    request_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.requests
        WHERE organization_id = %s
          AND request_definition_version_id = %s
          AND payload->>'message' IN ('First payload', 'Second payload')
        """,
        (fixture.organization_id, fixture.version_without_result_id),
    ).fetchone()
    assert request_count == (1,)

    correlation_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.external_correlations
        WHERE organization_id = %s
          AND correlation_kind = %s
          AND provider_key = %s
          AND external_key = %s
        """,
        (
            fixture.organization_id,
            correlation.correlation_kind,
            correlation.provider_key,
            correlation.external_key,
        ),
    ).fetchone()
    assert correlation_count == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_preexisting_unassigned_external_correlation_is_still_reserved(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)
    correlation = ExternalCorrelationInput(
        correlation_kind="provider_event",
        provider_key="n8n",
        external_key=f"event-{uuid4().hex}",
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.external_correlations (
            organization_id, correlation_kind, provider_key, external_key
        ) VALUES (%s, %s, %s, %s)
        """,
        (
            fixture.organization_id,
            correlation.correlation_kind,
            correlation.provider_key,
            correlation.external_key,
        ),
    )

    with pytest.raises(ExternalCorrelationConflict):
        await create_request(
            commands,
            _base_create_command(
                fixture,
                version_id=fixture.version_without_result_id,
                message="Must not steal reserved correlation",
                idempotency_key=f"reserved-correlation-{uuid4().hex}",
                correlations=(correlation,),
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_terminal_request_commands_serialize_on_request_row(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)
    created = await create_request(
        commands,
        _base_create_command(
            fixture,
            version_id=fixture.version_without_result_id,
            message="Race terminal state",
            idempotency_key=f"terminal-create-{uuid4().hex}",
        ),
    )

    completed, cancelled = await asyncio.gather(
        _capture(
            complete_request(
                commands,
                CompleteRequestCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    request_id=created.id,
                    expected_revision=1,
                    idempotency_key=f"terminal-complete-{uuid4().hex}",
                ),
            )
        ),
        _capture(
            cancel_request(
                commands,
                CancelRequestCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    request_id=created.id,
                    expected_revision=1,
                    reason="concurrent cancellation",
                    idempotency_key=f"terminal-cancel-{uuid4().hex}",
                ),
            )
        ),
    )
    outcomes = (completed, cancelled)
    assert sum(isinstance(item, Request) for item in outcomes) == 1
    assert sum(isinstance(item, RequestNotOpen) for item in outcomes) == 1

    row = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, created.id),
    ).fetchone()
    assert row is not None
    assert row[0] in ("completed", "cancelled")
    assert row[1] == 2

    terminal_event_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_kind = 'Request'
          AND aggregate_id = %s
          AND event_type IN ('request.completed.v1', 'request.cancelled.v1')
        """,
        (fixture.organization_id, created.id),
    ).fetchone()
    assert terminal_event_count == (1,)
