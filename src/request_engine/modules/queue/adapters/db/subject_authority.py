from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import SubjectAuthorityRequired
from request_engine.modules.tenancy.contracts.authority import AuthorityKind


@dataclass(frozen=True, slots=True)
class SubjectAuthorityEvidence:
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


async def require_subject_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    subject_party_id: UUID,
    scope_key: str,
    allow_operator_override: bool,
    lock_authority: bool = True,
) -> SubjectAuthorityEvidence:
    if allow_operator_override:
        return SubjectAuthorityEvidence(mode="operator", scope_key=scope_key)

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
            :subject_party_id,
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
                    "subject_party_id": subject_party_id,
                    "scope_key": scope_key,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SubjectAuthorityRequired(subject_party_id, scope_key)

    return SubjectAuthorityEvidence(
        mode="representation",
        scope_key=scope_key,
        representation_id=row["representation_id"],
        authority_kind=AuthorityKind(row["authority_kind"]),
    )
