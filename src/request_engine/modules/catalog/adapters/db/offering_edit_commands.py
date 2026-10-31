"""Offering rename and OfferingVersion supersession.

READ     idempotency receipt after exact ``operations.manage_terms`` authority;
LOCK     the Offering row ``FOR UPDATE`` (the same root used by booking-terms
         insertion and contextual booking), so a supersession serializes with
         concurrent supersessions, label edits and base-term configuration;
VALIDATE ``offerings.revision`` (rename) or the latest version id (supersede);
WRITE    the label, or version N+1 with copied requirements/policy/terms;
EMIT     audit plus a PII-free ``catalog.*`` outbox fact (ids and numbers only).

No row of an existing OfferingVersion, requirement, term or Reservation is
changed: earlier versions stay referenced exactly as booked.
"""

import json
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.commands.edit_offering import (
    OfferingState,
    SupersededBaseTermsState,
    SupersededOfferingVersionState,
    SupersedeOfferingVersionCommand,
    UpdateOfferingCommand,
    validate_supersede_offering_version,
    validate_update_offering,
)
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    CatalogInvalidInput,
    OfferingRevisionConflict,
    OfferingVersionSuperseded,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    require_operational_authority,
)

_UPDATE = "catalog.update_offering"
_SUPERSEDE = "catalog.supersede_offering_version"


class PostgresOfferingEditCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def update_offering(self, command: UpdateOfferingCommand) -> OfferingState:
        display_name = validate_update_offering(command)
        fingerprint = command_fingerprint(
            _UPDATE,
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "display_name": display_name,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_UPDATE,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _offering_from_json(cast(dict[str, object], replay["offering"]))
            current = await _lock_offering(session, command.organization_id, command.offering_id)
            current_revision = cast(int, current["revision"])
            if current_revision != command.expected_revision:
                raise OfferingRevisionConflict(
                    command.offering_id, command.expected_revision, current_revision
                )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.offerings
                               SET display_name = :display_name,
                                   updated_at = clock_timestamp()
                             WHERE organization_id = :organization_id AND id = :offering_id
                            RETURNING id, offering_key, display_name, active, revision
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_id": command.offering_id,
                            "display_name": display_name,
                        },
                    )
                )
                .mappings()
                .one()
            )
            state = OfferingState(
                offering_id=cast(UUID, row["id"]),
                offering_key=cast(str, row["offering_key"]),
                display_name=cast(str, row["display_name"]),
                active=cast(bool, row["active"]),
                revision=cast(int, row["revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_UPDATE,
                aggregate_kind="Offering",
                aggregate_id=command.offering_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "previous_revision": current_revision,
                    "new_revision": state.revision,
                    "previous_display_name": cast(str, current["display_name"]),
                    "display_name": state.display_name,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="catalog.offering_updated.v1",
                aggregate_kind="Offering",
                aggregate_id=command.offering_id,
                payload={"offering_id": str(command.offering_id), "revision": state.revision},
            )
            await complete_idempotency(
                session, idempotency_id, {"offering": _offering_to_json(state)}
            )
            return state

    async def supersede_offering_version(
        self, command: SupersedeOfferingVersionCommand
    ) -> SupersededOfferingVersionState:
        validate_supersede_offering_version(command)
        terms = command.booking_terms
        fingerprint = command_fingerprint(
            _SUPERSEDE,
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "expected_current_offering_version_id": (
                    command.expected_current_offering_version_id
                ),
                "duration_minutes": command.duration_minutes,
                "booking_terms": (
                    None
                    if terms is None
                    else {"amount": str(terms.amount.normalize()), "currency": terms.currency}
                ),
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
            )
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_SUPERSEDE,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _version_from_json(cast(dict[str, object], replay["offering_version"]))
            offering = await _lock_offering(session, command.organization_id, command.offering_id)
            if offering["active"] is not True:
                raise CatalogConfigurationConflict(
                    "Offering is inactive; a new OfferingVersion cannot be created"
                )
            current = await _latest_version(session, command.organization_id, command.offering_id)
            current_id = cast(UUID, current["id"])
            if current_id != command.expected_current_offering_version_id:
                raise OfferingVersionSuperseded(
                    command.offering_id,
                    command.expected_current_offering_version_id,
                    current_id,
                )
            current_terms = await _base_terms(session, command.organization_id, current_id)
            duration = (
                command.duration_minutes
                if command.duration_minutes is not None
                else cast(int | None, current["duration_minutes"])
            )
            if _is_noop(command, current, current_terms):
                raise CatalogInvalidInput(
                    "duration_minutes and booking_terms equal the current OfferingVersion"
                )
            version = cast(int, current["version"]) + 1
            version_id = await _insert_version(
                session, command.organization_id, command.offering_id, current, version, duration
            )
            requirement_count = await _copy_requirements(
                session, command.organization_id, current_id, version_id
            )
            new_terms = await _insert_terms(
                session,
                command.organization_id,
                version_id,
                (terms.amount, terms.currency)
                if terms is not None
                else (
                    None
                    if current_terms is None
                    else (
                        cast(Decimal, current_terms["amount"]),
                        cast(str, current_terms["currency"]),
                    )
                ),
            )
            state = SupersededOfferingVersionState(
                offering_id=command.offering_id,
                offering_version_id=version_id,
                version=version,
                previous_offering_version_id=current_id,
                duration_minutes=duration,
                booking_terms=new_terms,
                requirement_count=requirement_count,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_SUPERSEDE,
                aggregate_kind="Offering",
                aggregate_id=command.offering_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "previous_offering_version_id": str(current_id),
                    "offering_version_id": str(version_id),
                    "version": version,
                    "previous_duration_minutes": current["duration_minutes"],
                    "duration_minutes": duration,
                    "previous_amount": (
                        None if current_terms is None else str(current_terms["amount"])
                    ),
                    "amount": None if new_terms is None else str(new_terms.amount),
                    "currency": None if new_terms is None else new_terms.currency,
                    "requirement_count": requirement_count,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="catalog.offering_version_superseded.v1",
                aggregate_kind="Offering",
                aggregate_id=command.offering_id,
                payload={
                    "offering_id": str(command.offering_id),
                    "offering_version_id": str(version_id),
                    "previous_offering_version_id": str(current_id),
                    "version": version,
                },
            )
            await complete_idempotency(
                session, idempotency_id, {"offering_version": _version_to_json(state)}
            )
            return state


async def _lock_offering(
    session: AsyncSession, organization_id: UUID, offering_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, display_name, active, revision
                    FROM request_engine.offerings
                    WHERE organization_id = :organization_id AND id = :offering_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "offering_id": offering_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise CatalogConfigurationConflict("Offering is missing or belongs to another Organization")
    return row


async def _latest_version(
    session: AsyncSession, organization_id: UUID, offering_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT ov.id, ov.version, ov.duration_minutes, ov.bookable, ov.requestable,
                           ov.public_data, ov.delivery_policy,
                           COALESCE(
                               (
                                   SELECT pol.booking_policy
                                   FROM request_engine.offering_version_booking_policies pol
                                   WHERE pol.organization_id = ov.organization_id
                                     AND pol.offering_version_id = ov.id
                                   ORDER BY pol.revision DESC
                                   LIMIT 1
                               ),
                               ov.booking_policy
                           ) AS effective_booking_policy
                    FROM request_engine.offering_versions ov
                    WHERE ov.organization_id = :organization_id AND ov.offering_id = :offering_id
                    ORDER BY ov.version DESC, ov.id DESC
                    LIMIT 1
                    """
                ),
                {"organization_id": organization_id, "offering_id": offering_id},
            )
        )
        .mappings()
        .one()
    )


async def _base_terms(
    session: AsyncSession, organization_id: UUID, offering_version_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT amount, currency
                    FROM request_engine.offering_version_booking_terms
                    WHERE organization_id = :organization_id
                      AND offering_version_id = :offering_version_id
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"organization_id": organization_id, "offering_version_id": offering_version_id},
            )
        )
        .mappings()
        .first()
    )


def _is_noop(
    command: SupersedeOfferingVersionCommand,
    current: RowMapping,
    current_terms: RowMapping | None,
) -> bool:
    duration_same = (
        command.duration_minutes is None or command.duration_minutes == current["duration_minutes"]
    )
    terms = command.booking_terms
    terms_same = terms is None or (
        current_terms is not None
        and terms.amount == cast(Decimal, current_terms["amount"])
        and terms.currency == current_terms["currency"]
    )
    return duration_same and terms_same


async def _insert_version(
    session: AsyncSession,
    organization_id: UUID,
    offering_id: UUID,
    current: RowMapping,
    version: int,
    duration: int | None,
) -> UUID:
    return cast(
        UUID,
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.offering_versions (
                        organization_id, offering_id, version, duration_minutes,
                        bookable, requestable, booking_policy, public_data, delivery_policy
                    ) VALUES (
                        :organization_id, :offering_id, :version, :duration_minutes,
                        :bookable, :requestable, CAST(:booking_policy AS jsonb),
                        CAST(:public_data AS jsonb), CAST(:delivery_policy AS jsonb)
                    ) RETURNING id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_id": offering_id,
                    "version": version,
                    "duration_minutes": duration,
                    "bookable": current["bookable"],
                    "requestable": current["requestable"],
                    "booking_policy": _jsonb(current["effective_booking_policy"]),
                    "public_data": _jsonb(current["public_data"]),
                    "delivery_policy": _jsonb(current["delivery_policy"]),
                },
            )
        ).scalar_one(),
    )


async def _copy_requirements(
    session: AsyncSession, organization_id: UUID, source_id: UUID, target_id: UUID
) -> int:
    result = await session.execute(
        text(
            """
            INSERT INTO request_engine.offering_resource_requirements (
                organization_id, offering_version_id, capability_id, ordinal, quantity
            )
            SELECT organization_id, :target_id, capability_id, ordinal, quantity
            FROM request_engine.offering_resource_requirements
            WHERE organization_id = :organization_id AND offering_version_id = :source_id
            ORDER BY ordinal
            RETURNING id
            """
        ),
        {"organization_id": organization_id, "source_id": source_id, "target_id": target_id},
    )
    return len(result.all())


async def _insert_terms(
    session: AsyncSession,
    organization_id: UUID,
    offering_version_id: UUID,
    terms: tuple[Decimal, str] | None,
) -> SupersededBaseTermsState | None:
    if terms is None:
        return None
    amount, currency = terms
    terms_id = cast(
        UUID,
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.offering_version_booking_terms (
                        organization_id, offering_version_id, amount, currency
                    ) VALUES (:organization_id, :offering_version_id, :amount, :currency)
                    RETURNING id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                    "amount": amount,
                    "currency": currency,
                },
            )
        ).scalar_one(),
    )
    return SupersededBaseTermsState(terms_id=terms_id, amount=amount, currency=currency)


def _jsonb(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def _offering_to_json(state: OfferingState) -> dict[str, object]:
    return {
        "offering_id": str(state.offering_id),
        "offering_key": state.offering_key,
        "display_name": state.display_name,
        "active": state.active,
        "revision": state.revision,
    }


def _offering_from_json(value: dict[str, object]) -> OfferingState:
    return OfferingState(
        offering_id=UUID(cast(str, value["offering_id"])),
        offering_key=cast(str, value["offering_key"]),
        display_name=cast(str, value["display_name"]),
        active=cast(bool, value["active"]),
        revision=cast(int, value["revision"]),
    )


def _version_to_json(state: SupersededOfferingVersionState) -> dict[str, object]:
    terms = state.booking_terms
    return {
        "offering_id": str(state.offering_id),
        "offering_version_id": str(state.offering_version_id),
        "version": state.version,
        "previous_offering_version_id": str(state.previous_offering_version_id),
        "duration_minutes": state.duration_minutes,
        "booking_terms": None
        if terms is None
        else {
            "terms_id": str(terms.terms_id),
            "amount": str(terms.amount),
            "currency": terms.currency,
        },
        "requirement_count": state.requirement_count,
    }


def _version_from_json(value: dict[str, object]) -> SupersededOfferingVersionState:
    raw_terms = cast(dict[str, object] | None, value.get("booking_terms"))
    return SupersededOfferingVersionState(
        offering_id=UUID(cast(str, value["offering_id"])),
        offering_version_id=UUID(cast(str, value["offering_version_id"])),
        version=cast(int, value["version"]),
        previous_offering_version_id=UUID(cast(str, value["previous_offering_version_id"])),
        duration_minutes=cast(int | None, value.get("duration_minutes")),
        booking_terms=None
        if raw_terms is None
        else SupersededBaseTermsState(
            terms_id=UUID(cast(str, raw_terms["terms_id"])),
            amount=Decimal(cast(str, raw_terms["amount"])),
            currency=cast(str, raw_terms["currency"]),
        ),
        requirement_count=cast(int, value["requirement_count"]),
    )
