from uuid import UUID

from sqlalchemy import text

from request_engine.modules.communications.adapters.db.reminder_authority import REMINDER_MANAGE_SCOPE
from request_engine.modules.communications.adapters.db.reminder_commands import reminder_plan_from_row
from request_engine.modules.communications.contracts.reminders import ReminderPlan
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresReminderPlanReader:
    """Read ReminderPlans without leaking rows outside current Party authority."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_reminder_plan(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        reminder_plan_id: UUID,
        allow_subject_override: bool,
    ) -> ReminderPlan | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            if allow_subject_override:
                sql = text(
                    """
                    SELECT rp.*
                    FROM request_engine.reminder_plans rp
                    WHERE rp.organization_id = :organization_id
                      AND rp.id = :reminder_plan_id
                    """
                )
            else:
                sql = text(
                    """
                    SELECT rp.*
                    FROM request_engine.reminder_plans rp
                    WHERE rp.organization_id = :organization_id
                      AND rp.id = :reminder_plan_id
                      AND EXISTS (
                          SELECT 1
                          FROM request_engine.resolve_current_party_authority(
                              :organization_id,
                              :principal_id,
                              rp.subject_party_id,
                              :scope_key
                          )
                      )
                    """
                )
            row = (
                (
                    await session.execute(
                        sql,
                        {
                            "organization_id": organization_id,
                            "principal_id": principal_id,
                            "reminder_plan_id": reminder_plan_id,
                            "scope_key": REMINDER_MANAGE_SCOPE,
                        },
                    )
                )
                .mappings()
                .first()
            )
            return reminder_plan_from_row(row) if row is not None else None
