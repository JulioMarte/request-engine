from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresOperationalAuthorityPartyReader:
    """Resolve the single party a principal holds current operational authority for.

    Fail-closed: zero or multiple distinct represented parties yield None so
    callers refuse instead of guessing.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def resolve_operational_party(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        scope_keys: frozenset[str],
    ) -> UUID | None:
        if not scope_keys:
            raise ValueError("scope_keys must not be empty")

        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT DISTINCT r.represented_party_id
                            FROM request_engine.representations r
                            JOIN request_engine.principals p
                              ON p.organization_id = r.organization_id
                             AND p.id = r.principal_id
                            JOIN request_engine.parties party
                              ON party.organization_id = r.organization_id
                             AND party.id = r.represented_party_id
                            CROSS JOIN LATERAL (
                                SELECT clock_timestamp() AS db_now
                            ) clock
                            WHERE r.organization_id = :organization_id
                              AND r.principal_id = :principal_id
                              AND r.scope_key = ANY(:scope_keys)
                              AND r.status = 'active'
                              AND p.active
                              AND party.active
                              AND r.valid_from <= clock.db_now
                              AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "principal_id": principal_id,
                            "scope_keys": sorted(scope_keys),
                        },
                    )
                )
                .scalars()
                .all()
            )

        parties = {row for row in rows}
        if len(parties) != 1:
            return None
        return next(iter(parties))
