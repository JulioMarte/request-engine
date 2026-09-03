"""IntegrityError narrowing and typed-conflict resolution for party registry writes."""

from collections.abc import Sequence
from typing import Never, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.errors import (
    PartyContactPointExists,
    PartyDocumentConflict,
)
from request_engine.modules.tenancy.contracts.party_registry import PartyDocumentInput
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_UNIQUE_SQLSTATE = "23505"
_DOCUMENT_VALUE_UNIQUE = "party_identity_documents_active_value_uq"
_DOCUMENT_KIND_UNIQUE = "party_identity_documents_one_active_per_kind_uq"
_CONTACT_POINT_UNIQUE = "party_contact_points_organization_id_party_id_channel_norma_key"


def _reports_constraint(exc: IntegrityError, constraint: str) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    reported = getattr(diagnostic, "constraint_name", None)
    if reported is not None:
        return reported == constraint
    return f'"{constraint}"' in str(exc.orig)


def _unique_violation(exc: IntegrityError, constraint: str) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _UNIQUE_SQLSTATE and _reports_constraint(
        exc, constraint
    )


def is_document_value_violation(exc: IntegrityError) -> bool:
    return _unique_violation(exc, _DOCUMENT_VALUE_UNIQUE)


def is_document_kind_violation(exc: IntegrityError) -> bool:
    return _unique_violation(exc, _DOCUMENT_KIND_UNIQUE)


def is_contact_point_violation(exc: IntegrityError) -> bool:
    return _unique_violation(exc, _CONTACT_POINT_UNIQUE)


_CONFLICTING_DOCUMENT_SQL = text(
    """
    SELECT d.party_id, p.display_name
    FROM request_engine.party_identity_documents d
    JOIN request_engine.parties p
      ON p.organization_id = d.organization_id AND p.id = d.party_id
    WHERE d.organization_id = :organization_id
      AND d.kind = :kind
      AND d.authority IS NOT DISTINCT FROM :authority
      AND d.normalized_value = :value
      AND d.active
    LIMIT 1
    """
)


async def raise_document_conflict(
    session_factory: SessionFactory,
    organization_id: UUID,
    documents: Sequence[PartyDocumentInput],
    exc: IntegrityError,
) -> Never:
    if not (is_document_value_violation(exc) or is_document_kind_violation(exc)):
        raise exc
    async with tenant_transaction(session_factory, organization_id) as session:
        for document in documents:
            row = (
                (
                    await session.execute(
                        _CONFLICTING_DOCUMENT_SQL,
                        {
                            "organization_id": organization_id,
                            "kind": document.kind,
                            "authority": document.authority,
                            "value": document.value,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                raise PartyDocumentConflict(
                    "identity document value already registered for another party",
                    existing_party_id=cast(UUID, row["party_id"]),
                    existing_display_name=cast(str, row["display_name"]),
                ) from None
    raise exc


async def raise_added_document_conflict(
    session_factory: SessionFactory,
    organization_id: UUID,
    party_id: UUID,
    document: PartyDocumentInput,
    exc: IntegrityError,
) -> Never:
    if is_document_kind_violation(exc):
        raise PartyDocumentConflict(
            "party already holds an active document for this kind and authority",
            existing_party_id=party_id,
        ) from None
    await raise_document_conflict(session_factory, organization_id, (document,), exc)


def raise_contact_point_conflict(
    command: AddPartyContactPointCommand,
    exc: IntegrityError,
) -> Never:
    if not is_contact_point_violation(exc):
        raise exc
    raise PartyContactPointExists(command.party_id, command.channel, command.value) from None
