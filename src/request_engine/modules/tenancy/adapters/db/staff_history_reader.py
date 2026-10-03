"""Tenant-RLS history projection; free-form audit data never crosses this boundary."""

from typing import cast

from sqlalchemy import text

from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
)
from request_engine.modules.tenancy.application.queries.staff_history import (
    ListStaffHistoryQuery,
    StaffHistoryCommand,
    StaffHistoryEntry,
    StaffHistoryPage,
    StaffHistoryRevisionKind,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _revision(value: str | None) -> int | None:
    # Audit history can predate a typed writer. Never expose/cast arbitrary payloads.
    if value is None or not value.isascii() or not value.isdigit() or len(value) > 18:
        return None
    return int(value)


class PostgresStaffHistoryReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_history(
        self, actor: ActorContext, query: ListStaffHistoryQuery
    ) -> StaffHistoryPage:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows("staff.read"):
            raise StaffMembershipForbidden("staff history requires HUMAN staff inspection")
        async with actor_transaction(self._session_factory, actor) as session:
            # Permission, target, cursor and page share one statement snapshot.
            # No read becomes cached authority; no authoritative locks or writes.
            rows = (
                (
                    await session.execute(
                        text("""
                    WITH access AS (
                        SELECT EXISTS (
                            SELECT 1 FROM request_engine.principals actor
                            JOIN request_engine.staff_memberships m
                              ON m.organization_id=actor.organization_id
                             AND m.principal_id=actor.id AND m.status='active'
                            JOIN request_engine.principal_authority_grants g
                              ON g.organization_id=actor.organization_id
                             AND g.principal_id=actor.id AND g.status='active'
                             AND g.authority_plane='tenant_control'
                             AND g.capability_key='staff.read'
                            WHERE actor.organization_id=:organization_id
                              AND actor.id=:actor_id AND actor.active
                              AND actor.principal_kind='human'
                        ) AS permitted
                    ), target AS (
                        SELECT m.id FROM request_engine.staff_memberships m
                        WHERE (SELECT permitted FROM access)
                          AND m.organization_id=:organization_id AND m.id=:membership_id
                    ), events AS (
                        SELECT a.id, a.actor_principal_id, a.created_at, a.command_name,
                               a.details->>'revision_before' AS revision_before,
                               a.details->>'revision_after' AS revision_after
                        FROM request_engine.audit_records a
                        WHERE EXISTS (SELECT 1 FROM target)
                          AND a.organization_id=:organization_id AND a.aggregate_id=:membership_id
                          AND (
                              (a.aggregate_kind='StaffMembership' AND a.command_name IN (
                                  'staff.invite','staff.manage_authority','staff.manage_membership'))
                              OR (a.aggregate_kind='StaffMemberProfile'
                                  AND a.command_name='staff.profile.update')
                          )
                    ), anchor AS (
                        SELECT id,created_at FROM events WHERE id=CAST(:after AS uuid)
                    )
                    SELECT access.permitted, EXISTS(SELECT 1 FROM target) AS target_exists,
                           (CAST(:after AS uuid) IS NULL OR EXISTS(SELECT 1 FROM anchor))
                               AS cursor_valid,
                           page.*
                    FROM access LEFT JOIN LATERAL (
                        SELECT * FROM events
                        WHERE CAST(:after AS uuid) IS NULL OR
                              (created_at,id)<(SELECT created_at,id FROM anchor)
                        ORDER BY created_at DESC,id DESC LIMIT :fetch_limit
                    ) page ON true
                    ORDER BY page.created_at DESC,page.id DESC
                    """),
                        {
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                            "membership_id": query.membership_id,
                            "after": query.after,
                            "fetch_limit": query.limit + 1,
                        },
                    )
                )
                .mappings()
                .all()
            )
        if not rows[0]["permitted"]:
            raise StaffMembershipForbidden("staff history authority was denied")
        if not rows[0]["target_exists"]:
            raise StaffMembershipNotFound("staff membership is not visible in this tenant")
        if not rows[0]["cursor_valid"]:
            raise StaffMembershipInputInvalid("staff history cursor is invalid")
        records = [row for row in rows if row["id"] is not None]
        revision_kinds: dict[str, StaffHistoryRevisionKind] = {
            "staff.invite": "membership",
            "staff.manage_authority": "authority",
            "staff.manage_membership": "membership",
            "staff.profile.update": "profile",
        }
        entries = tuple(
            StaffHistoryEntry(
                event_id=row["id"],
                actor_principal_id=row["actor_principal_id"],
                occurred_at=row["created_at"],
                command_name=cast(StaffHistoryCommand, row["command_name"]),
                revision_kind=revision_kinds[row["command_name"]],
                revision_before=_revision(row["revision_before"]),
                revision_after=_revision(row["revision_after"]),
            )
            for row in records[: query.limit]
        )
        return StaffHistoryPage(
            items=entries,
            next_cursor=entries[-1].event_id if len(records) > query.limit else None,
        )
