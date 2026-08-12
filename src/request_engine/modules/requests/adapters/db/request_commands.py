import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.requests.adapters.db.party_authority import (
    RequestPartyAuthorityEvidence,
    require_requester_authority,
)
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


@dataclass(frozen=True, slots=True)
class RequestDefinitionVersionData:
    id: UUID
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None
    definition_active: bool


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
                return _request_from_replay(replay)

            version = await load_request_definition_version(
                session,
                organization_id=command.organization_id,
                version_id=command.request_definition_version_id,
            )
            if not version.definition_active:
                raise RequestDefinitionInactive(command.request_definition_version_id)
            _validate_schema_and_document(command.payload, version.input_schema)
            if version.result_schema is not None:
                validate_request_schema(version.result_schema)

            await validate_request_parties(session, command)
            authority = await _resolve_submit_authority(session, command)
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
            await _insert_participants(session, command, request_id)
            await _insert_correlations(session, command, request_id)

            request = await read_request(session, command.organization_id, request_id)
            await _record_command_success(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                request=request,
                idempotency_id=idempotency_id,
                event_type="request.created.v1",
                audit_details={
                    "request_definition_version_id": str(request.request_definition_version_id),
                    "participant_count": len(request.participants),
                    "correlation_count": len(request.correlations),
                    "party_authority": authority.audit_details(),
                },
                event_payload={
                    "request_definition_version_id": str(request.request_definition_version_id),
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
                },
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
                return _request_from_replay(replay)

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
            _validate_schema_and_document(command.result_payload, version.result_schema)

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
            await _record_command_success(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                request=request,
                idempotency_id=idempotency_id,
                event_type="request.result_recorded.v1",
                audit_details={"revision": request.revision},
                event_payload={"result_payload": request.result_payload},
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
                return _request_from_replay(replay)

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
            result_to_store = _validate_completion_result(
                command,
                version,
                existing_result=cast(dict[str, object] | None, row["result_payload"]),
            )
            serialized_result = _json(result_to_store) if result_to_store is not None else None
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
                    "result_payload": serialized_result,
                },
            )
            request = await read_request(session, command.organization_id, command.request_id)
            await _record_command_success(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                request=request,
                idempotency_id=idempotency_id,
                event_type="request.completed.v1",
                audit_details={
                    "revision": request.revision,
                    "result_present": request.result_payload is not None,
                },
                event_payload={"result_payload": request.result_payload},
            )
            return request

    async def cancel_request(self, command: CancelRequestCommand) -> Request:
        capability = "requests.cancel"
        return await self._terminal_without_result(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            fingerprint=command_fingerprint(
                capability,
                {
                    "request_id": command.request_id,
                    "reason": command.reason,
                    "expected_revision": command.expected_revision,
                },
            ),
            capability=capability,
            target_status=RequestStatus.CANCELLED,
            details={"reason": command.reason},
            expected_revision=command.expected_revision,
            party_scope="requests.manage",
            allow_party_override=command.allow_party_override,
        )

    async def fail_request(self, command: FailRequestCommand) -> Request:
        capability = "requests.fail"
        details: dict[str, object] = {
            "error_class": command.error_class,
            "details": command.details,
        }
        return await self._terminal_without_result(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            fingerprint=command_fingerprint(
                capability,
                {
                    "request_id": command.request_id,
                    "error_class": command.error_class,
                    "details": command.details,
                    "expected_revision": command.expected_revision,
                },
            ),
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
        party_scope: str | None = None,
        allow_party_override: bool = False,
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
                return _request_from_replay(replay)

            row = await lock_request(
                session,
                organization_id=organization_id,
                request_id=request_id,
            )
            authority: RequestPartyAuthorityEvidence | None = None
            if party_scope is not None:
                authority = await require_requester_authority(
                    session,
                    organization_id=organization_id,
                    principal_id=principal_id,
                    requester_party_id=cast(UUID | None, row["requester_party_id"]),
                    scope_key=party_scope,
                    allow_operator_override=allow_party_override,
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
            audit_details = {**details, "revision": request.revision}
            if authority is not None:
                audit_details["party_authority"] = authority.audit_details()
            await _record_command_success(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability=capability,
                request=request,
                idempotency_id=idempotency_id,
                event_type=f"request.{target_status.value}.v1",
                audit_details=audit_details,
                event_payload=details,
            )
            return request


def _request_from_replay(replay: dict[str, object]) -> Request:
    raw_request = replay.get("request")
    if not isinstance(raw_request, dict):
        raise RuntimeError("completed Request idempotency record has no Request object")
    return request_from_json(cast(dict[str, object], raw_request))


async def _record_command_success(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    request: Request,
    idempotency_id: UUID,
    event_type: str,
    audit_details: dict[str, object],
    event_payload: dict[str, object],
) -> None:
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name=capability,
        aggregate_kind="Request",
        aggregate_id=request.id,
        idempotency_id=idempotency_id,
        details=audit_details,
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type=event_type,
        aggregate_kind="Request",
        aggregate_id=request.id,
        payload={
            "request_id": str(request.id),
            **event_payload,
            "revision": request.revision,
        },
    )
    await complete_idempotency(
        session,
        idempotency_id,
        {"request": request_to_json(request)},
    )


async def _resolve_submit_authority(
    session: AsyncSession,
    command: CreateRequestCommand,
) -> RequestPartyAuthorityEvidence:
    if command.requester_party_id is None:
        return RequestPartyAuthorityEvidence(mode="unattributed", scope_key="requests.submit")
    return await require_requester_authority(
        session,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        requester_party_id=command.requester_party_id,
        scope_key="requests.submit",
        allow_operator_override=command.allow_party_override,
    )


def _validate_completion_result(
    command: CompleteRequestCommand,
    version: RequestDefinitionVersionData,
    *,
    existing_result: dict[str, object] | None,
) -> dict[str, object] | None:
    if version.result_schema is None:
        if command.result_payload is not None:
            raise RequestResultNotDefined(version.id)
        return None

    validate_request_schema(version.result_schema)
    if command.result_payload is not None:
        if existing_result is not None:
            raise RequestResultAlreadyRecorded(command.request_id)
        validate_request_document(command.result_payload, version.result_schema)
        return command.result_payload
    if existing_result is None:
        raise RequestResultRequired(command.request_id)
    return None


def _validate_schema_and_document(
    document: dict[str, object],
    schema: dict[str, object],
) -> None:
    validate_request_schema(schema)
    validate_request_document(document, schema)


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
                           requester_party_id,
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
        existing_correlation_id = (
            await session.execute(
                text(
                    """
                    SELECT id
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
        if existing_correlation_id is not None:
            raise ExternalCorrelationConflict(
                correlation.correlation_kind,
                correlation.provider_key,
                correlation.external_key,
            )


async def _insert_participants(
    session: AsyncSession,
    command: CreateRequestCommand,
    request_id: UUID,
) -> None:
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


async def _insert_correlations(
    session: AsyncSession,
    command: CreateRequestCommand,
    request_id: UUID,
) -> None:
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
    return f"request-correlation:{organization_id}:{correlation_kind}:{provider_key}:{external_key}"


def _json(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )