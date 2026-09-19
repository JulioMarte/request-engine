from sqlalchemy import text

from request_engine.modules.tenancy.application.queries.self_authority import (
    AuthorityInspectionDenied,
    CurrentRepresentation,
    SelfAuthorityQuery,
    SelfAuthoritySnapshot,
)
from request_engine.modules.tenancy.contracts.authority import AuthorityKind
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext


class PostgresSelfAuthorityReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_self(
        self, actor: ActorContext, query: SelfAuthorityQuery
    ) -> SelfAuthoritySnapshot:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not actor.allows("authority.read_self"):
            raise AuthorityInspectionDenied("self inspection requires current authority")
        async with actor_transaction(self._session_factory, actor) as session:
            rows = (
                (
                    await session.execute(
                        text("""
                        SELECT caller.id AS principal_id, caller.authority_revision,
                               statement_timestamp() AS observed_at, relationship.*
                          FROM request_engine.principals caller
                          LEFT JOIN LATERAL (
                              SELECT r.id AS representation_id, r.represented_party_id,
                                     r.scope_key, r.authority_kind, r.revision,
                                     r.valid_from, r.valid_until
                                FROM request_engine.representations r
                                JOIN request_engine.parties party
                                  ON party.organization_id = r.organization_id
                                 AND party.id = r.represented_party_id AND party.active
                               WHERE r.organization_id = caller.organization_id
                                 AND r.principal_id = caller.id AND r.status = 'active'
                                 AND r.valid_from <= statement_timestamp()
                                 AND (r.valid_until IS NULL
                                      OR r.valid_until > statement_timestamp())
                                 AND (CAST(:after AS uuid) IS NULL OR r.id > :after)
                               ORDER BY r.id LIMIT :page_size
                          ) relationship ON true
                         WHERE caller.organization_id = :organization_id
                           AND caller.id = :principal_id AND caller.active
                           AND EXISTS (
                               SELECT 1 FROM request_engine.principal_authority_grants g
                                WHERE g.organization_id = caller.organization_id
                                  AND g.principal_id = caller.id AND g.status = 'active'
                                  AND g.authority_plane = 'operational'
                                  AND g.capability_key = 'authority.read_self'
                           )
                         ORDER BY relationship.representation_id
                    """),
                        {
                            "organization_id": actor.organization_id,
                            "principal_id": actor.principal_id,
                            "after": query.after,
                            "page_size": query.limit + 1,
                        },
                    )
                )
                .mappings()
                .all()
            )
        if not rows:
            raise AuthorityInspectionDenied("self inspection requires current authority")
        representations = tuple(
            CurrentRepresentation(
                representation_id=row["representation_id"],
                represented_party_id=row["represented_party_id"],
                scope_key=row["scope_key"],
                authority_kind=AuthorityKind(row["authority_kind"]),
                revision=row["revision"],
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
            )
            for row in rows
            if row["representation_id"] is not None
        )
        page = representations[: query.limit]
        return SelfAuthoritySnapshot(
            principal_id=rows[0]["principal_id"],
            authority_revision=rows[0]["authority_revision"],
            observed_at=rows[0]["observed_at"],
            representations=page,
            next_after=page[-1].representation_id if len(representations) > query.limit else None,
        )
