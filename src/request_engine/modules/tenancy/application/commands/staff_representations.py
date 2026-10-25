"""Delegation of exact business-Party Representation scopes to tenant staff.

A staff member's configuration capability (for example ``catalog.manage``) is
necessary but not sufficient: configuration owners also require an exact active
``operations.manage_*`` Representation of the business Party. A current HUMAN
``staff.manage_authority`` manager may delegate only scopes it holds through a
delegable Representation of the same Party; delegated rows are never delegable.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    MANAGE_DISCOVERY_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
)

DELEGABLE_STAFF_REPRESENTATION_SCOPES: frozenset[str] = frozenset(
    {
        MANAGE_OPERATIONAL_PROFILE_SCOPE,
        MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
        MANAGE_COMMERCIAL_TERMS_SCOPE,
        MANAGE_DISCOVERY_SCOPE,
    }
)


def validate_staff_representation_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(scopes)) != len(scopes):
        raise ValueError("desired_scopes must not contain duplicates")
    unknown = sorted(set(scopes) - DELEGABLE_STAFF_REPRESENTATION_SCOPES)
    if unknown:
        raise ValueError(f"unsupported Representation scope: {', '.join(unknown)}")
    return tuple(sorted(scopes))


@dataclass(frozen=True, slots=True)
class ReplaceStaffRepresentationsCommand:
    membership_id: UUID
    authority_party_id: UUID
    expected_authority_revision: int
    desired_scopes: tuple[str, ...]
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class StaffRepresentation:
    representation_id: UUID
    authority_party_id: UUID
    scope_key: str
    authority_kind: str
    delegable: bool
    granted_by_principal_id: UUID | None
    valid_from: datetime
    valid_until: datetime | None
    revision: int


@dataclass(frozen=True, slots=True)
class StaffRepresentationsState:
    membership_id: UUID
    principal_id: UUID
    authority_revision: int
    representations: tuple[StaffRepresentation, ...]


@dataclass(frozen=True, slots=True)
class ReplaceStaffRepresentationsResult:
    membership_id: UUID
    authority_party_id: UUID
    authority_revision: int
    scopes: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]


class StaffRepresentationCommands(Protocol):
    async def read_staff_representations(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffRepresentationsState: ...

    async def replace_staff_representations(
        self, actor: ActorContext, command: ReplaceStaffRepresentationsCommand
    ) -> ReplaceStaffRepresentationsResult: ...
