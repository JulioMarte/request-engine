from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
    PlanStaffAuthorityQuery,
    StaffAuthorityGrant,
    StaffAuthorityPlan,
    StaffMembershipSummary,
    StaffOverview,
)
from request_engine.modules.tenancy.application.staff_authority import (
    validate_staff_capabilities,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext, PrincipalKind


class PostgresStaffMembershipReader:
    """Inspect explicit standing authority; never advertise it as Party permission."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_overview(self, actor: ActorContext) -> StaffOverview:
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise StaffMembershipForbidden("staff inspection requires a HUMAN actor")
        async with actor_transaction(self._session_factory, actor) as session:
            row = (
                (
                    await session.execute(
                        text("""
                    SELECT access.permitted,
                           count(m.id) AS total,
                           count(m.id) FILTER (WHERE m.status = 'active') AS active,
                           count(m.id) FILTER (WHERE m.status = 'invited') AS invited,
                           count(m.id) FILTER (WHERE m.status = 'suspended') AS suspended,
                           count(m.id) FILTER (WHERE m.status = 'revoked') AS revoked
                      FROM (SELECT EXISTS (
                          SELECT 1 FROM request_engine.principals actor
                          JOIN request_engine.staff_memberships membership
                            ON membership.organization_id = actor.organization_id
                           AND membership.principal_id = actor.id
                           AND membership.status = 'active'
                          JOIN request_engine.principal_authority_grants grant_row
                            ON grant_row.organization_id = actor.organization_id
                           AND grant_row.principal_id = actor.id
                           AND grant_row.capability_key = 'staff.read'
                           AND grant_row.authority_plane = 'tenant_control'
                           AND grant_row.status = 'active'
                         WHERE actor.organization_id = :organization_id
                           AND actor.id = :actor_id AND actor.active
                           AND actor.principal_kind = 'human'
                      ) AS permitted) access
                      LEFT JOIN request_engine.staff_memberships m
                        ON access.permitted AND m.organization_id = :organization_id
                     GROUP BY access.permitted
                    """),
                        {
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            if not row["permitted"]:
                raise StaffMembershipForbidden("staff inspection authority was denied")
            return StaffOverview(
                total=int(row["total"]),
                active=int(row["active"]),
                invited=int(row["invited"]),
                suspended=int(row["suspended"]),
                revoked=int(row["revoked"]),
            )

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

    async def plan_authority(
        self, actor: ActorContext, query: PlanStaffAuthorityQuery
    ) -> StaffAuthorityPlan:
        may_plan = actor.allows("staff.plan_authority") or actor.allows("staff.manage_authority")
        if actor.principal_kind is not PrincipalKind.HUMAN or not may_plan:
            raise StaffMembershipForbidden("staff authority planning requires a HUMAN actor")
        if query.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = validate_staff_capabilities(query.desired_capabilities)
        async with actor_transaction(self._session_factory, actor) as session:
            row = (
                (
                    await session.execute(
                        text("""
                    WITH access AS (
                        SELECT EXISTS (
                            SELECT 1 FROM request_engine.principals actor
                            JOIN request_engine.staff_memberships membership
                              ON membership.organization_id = actor.organization_id
                             AND membership.principal_id = actor.id
                             AND membership.status = 'active'
                            JOIN request_engine.principal_authority_grants grant_row
                              ON grant_row.organization_id = actor.organization_id
                             AND grant_row.principal_id = actor.id
                             AND grant_row.capability_key IN (
                                 'staff.plan_authority', 'staff.manage_authority'
                             )
                             AND grant_row.authority_plane = 'tenant_control'
                             AND grant_row.status = 'active'
                           WHERE actor.organization_id = :organization_id
                             AND actor.id = :actor_id AND actor.active
                             AND actor.principal_kind = 'human'
                        ) AS permitted
                    ), target AS (
                        SELECT m.id AS membership_id, m.principal_id,
                               p.authority_revision
                          FROM request_engine.staff_memberships m
                          JOIN request_engine.principals p
                            ON p.organization_id = m.organization_id
                           AND p.id = m.principal_id
                         WHERE (SELECT permitted FROM access)
                           AND m.organization_id = :organization_id
                           AND m.id = :membership_id AND m.status = 'active'
                    ), ceiling AS (
                        SELECT g.capability_key
                          FROM request_engine.principal_authority_grants g
                         WHERE g.organization_id = :organization_id
                           AND g.principal_id = :actor_id
                           AND g.status = 'active' AND g.delegable
                           AND g.authority_plane IN ('tenant_control', 'operational')
                    )
                    SELECT (SELECT permitted FROM access) AS permitted,
                           target.membership_id, target.principal_id,
                           target.authority_revision,
                           COALESCE(ARRAY(
                               SELECT grant_row.capability_key
                                 FROM request_engine.principal_authority_grants grant_row
                                 JOIN ceiling
                                   ON ceiling.capability_key = grant_row.capability_key
                                WHERE grant_row.organization_id = :organization_id
                                  AND grant_row.principal_id = target.principal_id
                                  AND grant_row.status = 'active'
                                ORDER BY grant_row.capability_key
                           ), ARRAY[]::text[]) AS current_capabilities,
                           COALESCE(ARRAY(
                               SELECT requested
                                 FROM unnest(CAST(:desired AS text[])) requested
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM ceiling
                                     WHERE ceiling.capability_key = requested
                                )
                                ORDER BY requested
                           ), ARRAY[]::text[]) AS blocked_capabilities
                      FROM access LEFT JOIN target ON true
                    """),
                        {
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                            "membership_id": query.membership_id,
                            "desired": list(desired),
                        },
                    )
                )
                .mappings()
                .one()
            )
        if not row["permitted"]:
            raise StaffMembershipForbidden("staff authority planning was denied")
        if row["membership_id"] is None:
            raise StaffMembershipNotFound("staff membership is not visible in this tenant")
        if row["principal_id"] == actor.principal_id:
            raise StaffMembershipForbidden("staff authority self-replacement is forbidden")
        authority_revision = int(row["authority_revision"])
        if authority_revision != query.expected_authority_revision:
            raise StaffMembershipRevisionConflict("staff authority revision is stale")
        current = tuple(row["current_capabilities"])
        blocked = tuple(row["blocked_capabilities"])
        current_set = set(current)
        desired_set = set(desired)
        return StaffAuthorityPlan(
            membership_id=query.membership_id,
            authority_revision=authority_revision,
            current=current,
            desired=desired,
            added=tuple(sorted(desired_set - current_set)),
            removed=tuple(sorted(current_set - desired_set)),
            assignable=not blocked,
            blocked_capabilities=blocked,
        )

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
