"""Ingestion of persisted transport outcome reports into fenced delivery finalize.

Trust boundary: the event lease's provider_key/connection_key come from the
authenticated provider-event ingest surface, never from the payload. The
delivery row is resolved authoritatively by the (provider_key, provider
idempotency key) pair; a report about an unknown key is a durable no-op fact
(nothing is created), and a malformed report is rejected as typed poison work.
Finalize runs inside one tenant transaction and re-locks the delivery and task
itself, so the terminal-monotonicity fence is owned by the same fenced path the
reconcile polling uses: a late contradictory report can never downgrade a
terminal delivery state or emit a contradictory task fact.
"""

import logging
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
)
from request_engine.modules.communications.adapters.worker.delivery_outcome_interpretation import (
    MalformedDeliveryOutcomeReport,
    interpret_delivery_outcome,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import ProviderEventLease
from request_engine.platform.worker.runtime import RejectedWorkError

logger = logging.getLogger(__name__)


class DeliveryOutcomeEventHandler:
    """Map one persisted provider outcome report to the fenced delivery finalize."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def __call__(self, lease: ProviderEventLease) -> None:
        try:
            report = interpret_delivery_outcome(lease.payload)
        except MalformedDeliveryOutcomeReport as exc:
            raise RejectedWorkError(exc.error_class) from exc
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            delivery_id = await _resolve_delivery_id(
                session,
                organization_id=lease.organization_id,
                provider_key=lease.provider_key,
                provider_idempotency_key=report.provider_idempotency_key,
            )
            if delivery_id is None:
                logger.info(
                    "delivery_outcome_report_unknown_identity",
                    extra={
                        "provider_key": lease.provider_key,
                        "provider_idempotency_key": report.provider_idempotency_key,
                    },
                )
                return
            await finalize_provider_result(
                session,
                organization_id=lease.organization_id,
                delivery_id=delivery_id,
                result=report.result,
            )


async def _resolve_delivery_id(
    session: AsyncSession,
    *,
    organization_id: UUID,
    provider_key: str,
    provider_idempotency_key: str,
) -> UUID | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.communication_deliveries
                WHERE organization_id = :organization_id
                  AND provider_key = :provider_key
                  AND provider_idempotency_key = :provider_idempotency_key
                """
            ),
            {
                "organization_id": organization_id,
                "provider_key": provider_key,
                "provider_idempotency_key": provider_idempotency_key,
            },
        )
    ).scalar_one_or_none()
    return cast(UUID | None, row)
