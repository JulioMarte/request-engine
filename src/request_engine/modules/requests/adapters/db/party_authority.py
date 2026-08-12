from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.requests.application.errors import RequestPartyAuthorityRequired
from request_engine.modules.tenancy.contracts.authority import AuthorityKind


@dataclass(frozen=True, slots=True)
class RequestPartyAuthorityEvidence:
    mode: str
    scope_key: str
    representation_id: UUID | None = None
    authority_kind: AuthorityKind | None = None

    def audit_details(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "scope_key": self.scope_key,
            "representation_id": (
                str(self.representation_id) if self.representation_id is not None else None
            ),
            "authority_kind": (
                self.authority_kind.value if self.authority_kind is not None else None
            ),
        }


async def require_requester_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    requester_party_id: UUID | None,
    scope_key: str,
    allow_operator_override: bool,
) -> RequestPartyAuthorityEvidence:
    """Authorize one Request operation against its requester authority anchor.

    requester_party_id is the only Party field that grants caller-facing control
    over a Request. Recipient and RequestParticipant roles remain business facts.
    Requests without a requester anchor are operator-managed only.
    """

    if allow_operator_override:
        return RequestPartyAuthorityEvidence(mode="operator", scope_key=scope_key)
    if requester_party_id is None:
        raise RequestPartyAuthorityRequired(None, scope_key)

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT representation_id, authority_kind
                    FROM request_engine.resolve_current_party_authority(
                        :organization_id,
                        :principal_id,
                        :requester_party_id,
                        :scope_key
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "requester_party_id": requester_party_id,
                    "scope_key": scope_key,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise RequestPartyAuthorityRequired(requester_party_id, scope_key)

    return RequestPartyAuthorityEvidence(
        mode="representation",
        scope_key=scope_key,
        representation_id=row["representation_id"],
        authority_kind=AuthorityKind(row["authority_kind"]),
    )
