import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.requests.adapters.db.request_reader import read_request
from request_engine.modules.requests.adapters.db.serialization import (
    request_from_json,
    request_to_json,
)
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
)
from request_engine.modules.requests.application.commands.complete_request import (
    CompleteRequestCommand,
)
from request_engine.modules.requests.application.commands.create_request import (
    CreateRequestCommand,
)
from request_engine.modules.requests.application.commands.fail_request import FailRequestCommand
from request_engine.modules.requests.application.commands.record_request_result import (
    RecordRequestResultCommand,
)
from request_engine.modules.requests.application.errors import (
    ExternalCorrelationConflict,
    RequestDefinitionInactive,
    RequestDefinitionVersionNotFound,
    RequestNotFound,
    RequestNotOpen,
    RequestPartyNotUsable,
    RequestResultAlreadyRecorded,
    RequestResultNotDefined,
    RequestResultRequired,
    RequestRevisionConflict,
)
from request_engine.modules.requests.contracts.request import Request, RequestStatus
from request_engine.modules.requests.domain.schema_validation import (
    validate_request_document,
    validate_request_schema,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresRequestCommands:
    """Transactional Request commands with Request as lifecycle serialization root."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_request(self, command: CreateRequestCommand) -> Request:
        capability = "requests.submit"
        fingerprint = command_fingerprint(
            capability,
            {
                "request_definition_version_id": command.request_definition_version_id,
                "requester_party_id": command.requester_party_id,
                "recipient_party_id": command.recipient_party_id,
                "payload": command.payload,
                "participants": _participant_fingerprint(command),
                "correlations": _correlation_fingerprint(command),
            },
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return request_from_json(cast(dict[str, object], replay["request"]))

            version = await load_request_definition_version(
                session,
                organization_id=command.organization_id,
                version_id=command.request_definition_version_id,
            )
            if not version.definition_active:
                raise RequestDefinitionInactive(command.request_definition_version_id)

            validate_request_schema(version.input_schema)
            validate_request_document(command.payload, version.input_schema)
            if version.result_schema is not None:
                validate_request_schema(version.result_schema)

            await validate_request_parties(session, command)
            await lock_external_correlations(session, command)
            await assert_external_correlations_available(session, command)

            request_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.requests (
                                organization_id,
                                request_definition_version_id,
                                requester_party_id,
                                recipient_party_id,
                                payload
                            ) VALUES (
                                :organization_id,
                                :request_definition_version_id,
                                :requester_party_id,
                                :recipient_party_id,
                                CAST(:payload AS jsonb)
                            )
                            RETURNING id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "request_definition_version_id": (
                                command.request_definition_version_id
                            ),
                            "requester_party_id": command.requester_party_id,
                            "recipient_party_id": command.recipient_party_id,
                            "payload": _json(command.payload),
                        },
                    )
                ).scalar_one(),
            )

            for participant in command.participants:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.request_participants (
                            organization_id, request_id, party_id, role_key
                        ) VALUES (
                            :organization_id, :request_id, :party_id, :role_key
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "request_id": request_id,
                        "party_id": participant.party_id,
                        "role_key": participant.role_key,
                    },
                )

            for correlation in command.correlations:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.external_correlations (
                            organization_id,
                            request_id,
                            correlation_kind,
                            provider_key,
                            external_key
                        ) VALUES (
                            :organization_id,
                            :request_id,
                            :correlation_kind,
                            :provider_key,
                            :external_key
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "request_id": request_id,
                        "correlation_kind": correlation.correlation_kind,
                        "provider_key": correlation.provider_key,
                        "external_key": correlation.external_key,
                    },
                )

            request = await read_request(session, command.organization_id, request_id)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="Request",
                aggregate_id=request.id,
                idempotency_id=idempotency_id,
                details={
                    "request_definition_version_id": str(
                        request.request_definition_version_id
                    ),
                    "participant_count": len(request.participants),
                    "correlation_count": len(request.correlations),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="request.created.v1",
                aggregate_kind="Request",
                aggregate_id=request.id,
                payload={
                    "request_id": str(request.id),
                    "request_definition_version_id": str(
                        request.request_definition_version_id
                    ),
                    "requester_party_id": (
                        str(request.requester_party_id)
                        if request.requester_party_id is not None
                        else None
                    ),
                    "recipient_party_id": (
                        str(request.recipient_party_id)
                        if request.recipient_party_id is not None
                        else None
                    ),
                    "payload": request.payload,
                    "revision": request.revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"request": request_to_json(request)},
            )
            return request

    async def record_request_result(self, command: RecordRequestResultCommand) -> Request:
        capability = "requests.record_result"
        fingerprint = command_fingerprint(
            capability,
            {
                "request_id": command.request_id,
                "result_payload": command.result_payload,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return request_from_json(cast(dict[str, object], replay["request"]))

            row = await lock_request(
                session,
                organization_id=command.organization_id,
                request_id=command.request_id,
            )
            ensure_request_open(row, command.request_id)
            ensure_expected_revision(row, command.request_id, command.expected_revision)
            if row["result_payload"] is not None:
                raise RequestResultAlreadyRecorded(command.request_id)

            version = await load_request_definition_version(
                session,
                organization_id=command.organization_id,
                version_id=cast(UUID, row["request_definition_version_id"]),
            )
            if version.result_schema is None:
                raise RequestResultNotDefined(version.id)
            validate_request_schema(version.result_schema)
            validate_request_document(command.result_payload, version.result_schema)

            await session.execute(
                text(
                    """
                    UPDATE request_engine.requests
                    SET result_payload = CAST(:result_payload AS jsonb),
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :request_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "request_id": command.request_id,
                    "result_payload": _json(command.result_payload),
                },
            )
            request = await read_request(session, command.organization_id, command.request_id)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="Request",
                aggregate_id=request.id,
                idempotency_id=idempotency_id,
                details={"revision": request.revision},
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="request.result_recorded.v1",
                aggregate_kind="Request",
                aggregate_id=request.id,
                payload={
                    "request_id": str(request.id),
                    "result_payload": request.result_payload,
                    "revision": request.revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"request": request_to_json(request)},
            )
            return request

    async def complete_request(self, command: CompleteRequestCommand) -> Request:
        capability = "requests.complete"
        fingerprint = command_fingerprint(
            capability,
            {
                "request_id": command.request_id,
                "result_payload": command.result_payload,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return request_from_json(cast(dict[str, object], replay["request"]))

            row = await lock_request(
                session,
                organization_id=command.organization_id,
                request_id=command.request_id,
            )
            ensure_request_open(row, command.request_id)
            ensure_expected_revision(row, command.request_id, command.expected_revision)

            version = await load_request_definition_version(
                session,
                organization_id=command.organization_id,
                version_id=cast(UUID, row["request_definition_version_id"]),
            )
            existing_result = cast(dict[str, object] | None, row["result_payload"])
            result_to_store: dict[str, object] | None = None

            if version.result_schema is None:
                if command.result_payload is not None:
                    raise RequestResultNotDefined(version.id)
            else:
                validate_request_schema(version.result_schema)
                if command.result_payload is not None:
                    if existing_result is not None:
                        raise RequestResultAlreadyRecorded(command.request_id)
                    validate_request_document(command.result_payload, version.result_schema)
                    result_to_store = command.result_payload
                elif existing_result is None:
                    raise RequestResultRequired(command.request_id)

            await session.execute(
                text(
                    """
                    UPDATE request_engine.requests
                    SET status = 'completed',
                        result_payload = COALESCE(
                            CAST(:result_payload AS jsonb),
                            result_payload
                        ),
                        completed_at = clock_timestamp(),
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :request_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "request_id": command.request_id,
                    "result_payload": _json(result_to_store) if result_to_store is not None else None,
                },
            )
            request = await read_request(session, command.organization_id, command.request_id)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="Request",
                aggregate_id=request.id,
                idempotency_id=idempotency_id,
                details={
                    "revision": request.revision,
                    "result_present": request.result_payload is not None,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="request.completed.v1",
                aggregate_kind="Request",
                aggregate_id=request.id,
                payload={
                    "request_id": str(request.id),
                    "result_payload": request.result_payload,
                    "revision": request.revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"request": request_to_json(request)},
            )
            return request

    async def cancel_request(self, command: CancelRequestCommand) -> Request:
        capability = "requests.cancel"
        fingerprint = command_fingerprint(
            capability,
            {
                "request_id": command.request_id,
                "reason": command.reason,
                "expected_revision": command.expected_revision,
            },
        )
        return await self._terminal_without_result(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
            capability=capability,
            target_status=RequestStatus.CANCELLED,
            details={"reason": command.reason},
            expected_revision=command.expected_revision,
        )

    async def fail_request(self, command: FailRequestCommand) -> Request:
        capability = "requests.fail"
        fingerprint = command_fingerprint(
            capability,
            {
                "request_id": command.request_id,
                "error_class": command.error_class,
                "details": command.details,
                "expected_revision": command.expected_revision,
            },
        )
        details: dict[str, object] = {
            "error_class": command.error_class,
            "details": command.details,
        }
        return await self._terminal_without_result(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
            capability=capability,
            target_status=RequestStatus.FAILED,
            details=details,
            expected_revision=command.expected_revision,
        )

    async def _terminal_without_result(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        request_id: UUID,
        idempotency_key: str,
        fingerprint: str,
        capability: str,
        target_status: RequestStatus,
        details: dict[str, object],
        expected_revision: int | None,
    ) -> Request:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability=capability,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return request_from_json(cast(dict[str, object], replay["request"]))

            row = await lock_request(
                session,
                organization_id=organization_id,
                request_id=request_id,
            )
            ensure_request_open(row, request_id)
            ensure_expected_revision(row, request_id, expected_revision)

            await session.execute(
                text(
                    """
                    UPDATE request_engine.requests
                    SET status = :status,
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :request_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "request_id": request_id,
                    "status": target_status.value,
                },
            )
            request = await read_request(session, organization_id, request_id)
            await append_audit(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                command_name=capability,
                aggregate_kind="Request",
                aggregate_id=request.id,
                idempotency_id=idempotency_id,
                details={**details, "revision": request.revision},
            )
            await append_outbox(
                session,
                organization_id=organization_id,
                event_type=f"request.{target_status.value}.v1",
                aggregate_kind="Request",
                aggregate_id=request.id,
                payload={
                    "request_id": str(request.id),
                    **details,
                    "revision": request.revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"request": request_to_json(request)},
            )
            return request


class RequestDefinitionVersionData:
    def __init__(
        self,
        *,
        id: UUID,
        input_schema: dict[str, object],
        result_schema: dict[str, object] | None,
        definition_active: bool,
    ) -> None:
        self.id = id
        self.input_schema = input_schema
        self.result_schema = result_schema
        self.definition_active = definition_active


async def load_request_definition_version(
    session: AsyncSession,
    *,
    organization_id: UUID,
    version_id: UUID,
) -> RequestDefinitionVersionData:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT rdv.id,
                           rdv.input_schema,
                           rdv.result_schema,
                           rd.active AS definition_active
                    FROM request_engine.request_definition_versions AS rdv
                    JOIN request_engine.request_definitions AS rd
                      ON rd.organization_id = rdv.organization_id
                     AND rd.id = rdv.request_definition_id
                    WHERE rdv.organization_id = :organization_id
                      AND rdv.id = :version_id
                    """
                ),
                {"organization_id": organization_id, "version_id": version_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RequestDefinitionVersionNotFound(version_id)
    return RequestDefinitionVersionData(
        id=cast(UUID, row["id"]),
        input_schema=cast(dict[str, object], row["input_schema"]),
        result_schema=cast(dict[str, object] | None, row["result_schema"]),
        definition_active=cast(bool, row["definition_active"]),
    )


async def lock_request(
    session: AsyncSession,
    *,
    organization_id: UUID,
    request_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id,
                           request_definition_version_id,
                           status,
                           result_payload,
                           revision
                    FROM request_engine.requests
                    WHERE organization_id = :organization_id
                      AND id = :request_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "request_id": request_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RequestNotFound(request_id)
    return row


def ensure_request_open(row: RowMapping, request_id: UUID) -> None:
    status = cast(str, row["status"])
    if status != RequestStatus.OPEN.value:
        raise RequestNotOpen(request_id, status)


def ensure_expected_revision(
    row: RowMapping,
    request_id: UUID,
    expected_revision: int | None,
) -> None:
    if expected_revision is None:
        return
    actual = cast(int, row["revision"])
    if actual != expected_revision:
        raise RequestRevisionConflict(request_id, expected_revision, actual)


async def validate_request_parties(
    session: AsyncSession,
    command: CreateRequestCommand,
) -> None:
    party_ids = {
        party_id
        for party_id in (
            command.requester_party_id,
            command.recipient_party_id,
            *(participant.party_id for participant in command.participants),
        )
        if party_id is not None
    }
    for party_id in sorted(party_ids, key=str):
        active = (
            await session.execute(
                text(
                    """
                    SELECT active
                    FROM request_engine.parties
                    WHERE organization_id = :organization_id
                      AND id = :party_id
                    """
                ),
                {"organization_id": command.organization_id, "party_id": party_id},
            )
        ).scalar_one_or_none()
        if active is not True:
            raise RequestPartyNotUsable(party_id)


async def lock_external_correlations(
    session: AsyncSession,
    command: CreateRequestCommand,
) -> None:
    identities = sorted(
        {
            _correlation_identity(
                command.organization_id,
                correlation.correlation_kind,
                correlation.provider_key,
                correlation.external_key,
            )
            for correlation in command.correlations
        }
    )
    for identity in identities:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": identity},
        )


async def assert_external_correlations_available(
    session: AsyncSession,
    command: CreateRequestCommand,
) -> None:
    for correlation in command.correlations:
        existing_request_id = (
            await session.execute(
                text(
                    """
                    SELECT request_id
                    FROM request_engine.external_correlations
                    WHERE organization_id = :organization_id
                      AND correlation_kind = :correlation_kind
                      AND provider_key = :provider_key
                      AND external_key = :external_key
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "correlation_kind": correlation.correlation_kind,
                    "provider_key": correlation.provider_key,
                    "external_key": correlation.external_key,
                },
            )
        ).scalar_one_or_none()
        if existing_request_id is not None:
            raise ExternalCorrelationConflict(
                correlation.correlation_kind,
                correlation.provider_key,
                correlation.external_key,
            )


def _participant_fingerprint(command: CreateRequestCommand) -> list[dict[str, object]]:
    return [
        {"party_id": str(participant.party_id), "role_key": participant.role_key}
        for participant in sorted(
            command.participants,
            key=lambda item: (item.role_key, str(item.party_id)),
        )
    ]


def _correlation_fingerprint(command: CreateRequestCommand) -> list[dict[str, object]]:
    return [
        {
            "correlation_kind": correlation.correlation_kind,
            "provider_key": correlation.provider_key,
            "external_key": correlation.external_key,
        }
        for correlation in sorted(
            command.correlations,
            key=lambda item: (
                item.correlation_kind,
                item.provider_key,
                item.external_key,
            ),
        )
    ]


def _correlation_identity(
    organization_id: UUID,
    correlation_kind: str,
    provider_key: str,
    external_key: str,
) -> str:
    return (
        f"request-correlation:{organization_id}:"
        f"{correlation_kind}:{provider_key}:{external_key}"
    )


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
