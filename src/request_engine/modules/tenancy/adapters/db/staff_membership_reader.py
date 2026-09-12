from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipNotFound,
)
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
    StaffAuthorityGrant,
    StaffMembershipSummary,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext, PrincipalKind


class PostgresStaffMembershipReader:
    """Inspect explicit standing authority; never advertise it as Party permission."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_memberships(
        self, actor: ActorContext, query: ListStaffMembershipsQuery
    ) -> tuple[StaffMembershipSummary, ...]:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await self._read(actor, membership_id=None, after=query.after, limit=query.limit)

    async def read_membership(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffMembershipSummary:
        rows = await self._read(actor, membership_id=membership_id, after=None, limit=1)
        if not rows:
            raise StaffMembershipNotFound("staff membership is not visible in this tenant")
        return rows[0]

    async def _read(
        self, actor: ActorContext, *, membership_id: UUID | None, after: UUID | None, limit: int
    ) -> tuple[StaffMembershipSummary, ...]:
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff inspection requires a HUMAN actor")
        async with actor_transaction(self._session_factory, actor) as session:
            # Authorization and rows share one statement snapshot; no check/read race,
            # authoritative row locks, identity-provider calls or credential disclosure.
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT access.permitted, member.*
                  FROM (SELECT EXISTS (
                      SELECT 1 FROM request_engine.principals actor
                      JOIN request_engine.staff_memberships membership
                        ON membership.organization_id = actor.organization_id
                       AND membership.principal_id = actor.id AND membership.status = 'active'
                      JOIN request_engine.principal_authority_grants grant_row
                        ON grant_row.organization_id = actor.organization_id
                       AND grant_row.principal_id = actor.id
                       AND grant_row.capability_key = 'staff.read'
                       AND grant_row.authority_plane = 'tenant_control'
                       AND grant_row.status = 'active'
                     WHERE actor.organization_id = :organization_id AND actor.id = :actor_id
                       AND actor.active AND actor.principal_kind = 'human'
                  ) AS permitted) access
                  LEFT JOIN LATERAL (
                      SELECT m.id AS membership_id, m.principal_id, m.status,
                             m.revision AS membership_revision, p.authority_revision,
                             p.active AS principal_active, m.authority_anchor_party_id,
                             ARRAY(SELECT g.capability_key
                               FROM request_engine.principal_authority_grants g
                              WHERE g.organization_id = m.organization_id
                                AND g.principal_id = p.id AND g.status = 'active'
                              ORDER BY g.capability_key) AS capabilities,
                             ARRAY(SELECT g.capability_key
                               FROM request_engine.principal_authority_grants g
                              WHERE g.organization_id = m.organization_id
                                AND g.principal_id = p.id AND g.status = 'active' AND g.delegable
                              ORDER BY g.capability_key) AS delegable_capabilities
                        FROM request_engine.staff_memberships m
                        JOIN request_engine.principals p
                          ON p.organization_id = m.organization_id AND p.id = m.principal_id
                       WHERE access.permitted AND m.organization_id = :organization_id
                         AND (CAST(:membership_id AS uuid) IS NULL OR m.id = :membership_id)
                         AND (CAST(:after AS uuid) IS NULL OR m.id > :after)
                       ORDER BY m.id LIMIT :limit
                  ) member ON true
                 ORDER BY member.membership_id
            """),
                        {
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                            "membership_id": membership_id,
                            "after": after,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if not rows[0]["permitted"]:
                raise StaffMembershipForbidden("staff inspection authority was denied")
            return tuple(
                StaffMembershipSummary(
                    membership_id=row["membership_id"],
                    principal_id=row["principal_id"],
                    status=row["status"],
                    membership_revision=row["membership_revision"],
                    authority_revision=row["authority_revision"],
                    principal_active=row["principal_active"],
                    authority_anchor_party_id=row["authority_anchor_party_id"],
                    standing_grants=tuple(
                        StaffAuthorityGrant(key, key in row["delegable_capabilities"])
                        for key in row["capabilities"]
                    ),
                )
                for row in rows
                if row["membership_id"] is not None
            )
