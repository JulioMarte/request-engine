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
    lock_authority: bool = True,
) -> RequestPartyAuthorityEvidence:
    """Authorize one Request operation against its requester authority anchor.

    Mutations lock the current exact-scope Representation and its Principal/Party
    endpoints by default so a concurrent revoke/deactivation serializes after the
    already-authorized command. Read callers explicitly opt out of those locks.
    """

    if allow_operator_override:
        return RequestPartyAuthorityEvidence(mode="operator", scope_key=scope_key)
    if requester_party_id is None:
        raise RequestPartyAuthorityRequired(None, scope_key)

    function_name = (
        "request_engine.lock_current_party_authority"
        if lock_authority
        else "request_engine.resolve_current_party_authority"
    )
    query = text(
        f"""
        SELECT representation_id, authority_kind
        FROM {function_name}(
            :organization_id,
            :principal_id,
            :requester_party_id,
            :scope_key
        )
        """
    )
    row = (
        (
            await session.execute(
                query,
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
