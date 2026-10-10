from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.queries.self_organizations import SelfOrganization
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.freshness import RecoveryCompletionRequired


class PostgresSelfOrganizationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    async def list_for_subject(
        self, subject: AuthenticatedSubject, *, after: UUID | None, limit: int
    ) -> tuple[SelfOrganization, ...]:
        if subject.metadata.get("recovery_restricted", "").lower() == "true":
            raise RecoveryCompletionRequired("Complete identity recovery before tenant discovery")
        if subject.subject_class is not AuthenticatedSubjectClass.HUMAN:
            return ()
        if not 1 <= limit <= 101:
            raise ValueError("limit must be between 1 and 101")
        async with self._sessions() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM request_auth.read_self_organizations("
                            ":authority_id, :subject_id, :after, :limit)"
                        ),
                        {
                            "authority_id": UUID(subject.authority_id),
                            "subject_id": subject.subject_id,
                            "after": after,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(SelfOrganization(**dict(row)) for row in rows)
