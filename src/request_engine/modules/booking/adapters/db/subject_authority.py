from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.errors import SubjectAuthorityRequired
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
) -> SubjectAuthorityEvidence:
    """Resolve authority in the same transaction as the booking mutation.

    The operator path is an explicit policy decision made from authenticated
    actor permissions. Otherwise, a current exact-scope Representation must
    still exist at the database wall-clock instant of the authoritative write.
    """

    if allow_operator_override:
        return SubjectAuthorityEvidence(mode="operator", scope_key=scope_key)

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT r.id AS representation_id, r.authority_kind
                    FROM request_engine.representations r
                    JOIN request_engine.principals p
                      ON p.organization_id = r.organization_id
                     AND p.id = r.principal_id
                    JOIN request_engine.parties party
                      ON party.organization_id = r.organization_id
                     AND party.id = r.represented_party_id
                    CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
                    WHERE r.organization_id = :organization_id
                      AND r.principal_id = :principal_id
                      AND r.represented_party_id = :subject_party_id
                      AND r.scope_key = :scope_key
                      AND r.status = 'active'
                      AND p.active
                      AND party.active
                      AND r.valid_from <= clock.db_now
                      AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
                    ORDER BY r.valid_from DESC, r.id
                    LIMIT 1
                    """
                ),
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
