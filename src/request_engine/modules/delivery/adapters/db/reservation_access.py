import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.contracts.access import (
    AccessKind,
    AccessPolicy,
    AccessStatus,
    DeliveryWorkClaim,
    ProvisionedAccess,
    ReservationAccess,
    ReservationAccessSource,
    parse_delivery_policy,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.worker.runtime import LeaseLostWorkError


class PostgresDeliveryPolicyReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_access_policies(
        self, organization_id: UUID, offering_version_id: UUID
    ) -> tuple[AccessPolicy, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            raw = (
                await session.execute(
                    text(
                        """
                        SELECT delivery_policy
                        FROM request_engine.offering_versions
                        WHERE organization_id = :organization_id
                          AND id = :offering_version_id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "offering_version_id": offering_version_id,
                    },
                )
            ).scalar_one()
        return parse_delivery_policy(raw)


class PostgresReservationAccessRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def confirmed_source_is_current(
        self,
        source: ReservationAccessSource,
        work_claim: DeliveryWorkClaim,
    ) -> bool:
        async with tenant_transaction(self._session_factory, source.organization_id) as session:
            await self._lock_work_claim(session, work_claim)
            found = (
                await session.execute(
                    text(
                        """
                        SELECT true
                        FROM request_engine.reservations
                        WHERE organization_id = :organization_id
                          AND id = :reservation_id
                          AND offering_version_id = :offering_version_id
                          AND status = 'confirmed'
                          AND revision = :reservation_revision
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": source.organization_id,
                        "reservation_id": source.reservation_id,
                        "offering_version_id": source.offering_version_id,
                        "reservation_revision": source.revision,
                    },
                )
            ).scalar_one_or_none()
        return bool(found)

    async def get_by_key(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        reservation_revision: int,
        access_key: str,
    ) -> ReservationAccess | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_read.reservation_access_v1
                            WHERE organization_id = :organization_id
                              AND reservation_id = :reservation_id
                              AND reservation_revision = :reservation_revision
                              AND access_key = :access_key
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "reservation_id": reservation_id,
                            "reservation_revision": reservation_revision,
                            "access_key": access_key,
                        },
                    )
                )
                .mappings()
                .first()
            )
        return _from_row(row) if row is not None else None

    async def ensure_pending(
        self,
        source: ReservationAccessSource,
        policy: AccessPolicy,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess | None:
        materialization_key = (
            f"reservation-access:{source.reservation_id}:{policy.access_key}:r{source.revision}"
        )
        async with tenant_transaction(self._session_factory, source.organization_id) as session:
            await self._lock_work_claim(session, work_claim)
            current = (
                await session.execute(
                    text(
                        """
                        SELECT true
                        FROM request_engine.reservations
                        WHERE organization_id = :organization_id
                          AND id = :reservation_id
                          AND offering_version_id = :offering_version_id
                          AND status = 'confirmed'
                          AND revision = :reservation_revision
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": source.organization_id,
                        "reservation_id": source.reservation_id,
                        "offering_version_id": source.offering_version_id,
                        "reservation_revision": source.revision,
                    },
                )
            ).scalar_one_or_none()
            if not current:
                return None

            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.reservation_access (
                        organization_id, reservation_id, reservation_revision,
                        access_key, kind, provider_key, materialization_key, status
                    )
                    VALUES (
                        :organization_id, :reservation_id, :reservation_revision,
                        :access_key, :kind, :provider_key, :materialization_key, 'pending'
                    )
                    ON CONFLICT (
                        organization_id, reservation_id, reservation_revision, access_key
                    ) DO NOTHING
                    """
                ),
                {
                    "organization_id": source.organization_id,
                    "reservation_id": source.reservation_id,
                    "reservation_revision": source.revision,
                    "access_key": policy.access_key,
                    "kind": policy.kind.value,
                    "provider_key": policy.provider_key,
                    "materialization_key": materialization_key,
                },
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.reservation_access
                            WHERE organization_id = :organization_id
                              AND reservation_id = :reservation_id
                              AND reservation_revision = :reservation_revision
                              AND access_key = :access_key
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": source.organization_id,
                            "reservation_id": source.reservation_id,
                            "reservation_revision": source.revision,
                            "access_key": policy.access_key,
                        },
                    )
                )
                .mappings()
                .one()
            )
            access = _from_row(row)
            if (
                access.materialization_key != materialization_key
                or access.kind is not policy.kind
                or access.provider_key != policy.provider_key
            ):
                raise RuntimeError("reservation_access_policy_conflict")
            return access

    async def record_materialized(
        self,
        claim: ReservationAccess,
        materialized: ProvisionedAccess,
    ) -> ReservationAccess:
        """Record provider evidence without publishing access authority.

        This intentionally does not require the Outbox lease. A process may
        lose its lease after provider I/O; preserving the idempotent provider
        evidence lets the next claimant reconcile instead of blindly creating
        another artifact. READY/REVOKED transitions remain fenced.
        """
        async with tenant_transaction(self._session_factory, claim.organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.reservation_access
                               SET access_uri = :access_uri,
                                   external_ref = :external_ref,
                                   public_data = CAST(:public_data AS jsonb),
                                   provisioned_at = clock_timestamp(),
                                   revision = revision + 1
                             WHERE organization_id = :organization_id
                               AND id = :access_id
                               AND status = 'pending'
                               AND revision = :row_revision
                               AND provisioned_at IS NULL
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": claim.organization_id,
                            "access_id": claim.id,
                            "row_revision": claim.revision,
                            "access_uri": materialized.access_uri,
                            "external_ref": materialized.external_ref,
                            "public_data": json.dumps(materialized.public_data),
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT *
                                FROM request_engine.reservation_access
                                WHERE organization_id = :organization_id
                                  AND id = :access_id
                                """
                            ),
                            {
                                "organization_id": claim.organization_id,
                                "access_id": claim.id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
        return _from_row(row)

    async def publish_ready_if_current(
        self,
        source: ReservationAccessSource,
        claim: ReservationAccess,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess | None:
        async with tenant_transaction(self._session_factory, source.organization_id) as session:
            await self._lock_work_claim(session, work_claim)
            current = (
                await session.execute(
                    text(
                        """
                        SELECT true
                        FROM request_engine.reservations
                        WHERE organization_id = :organization_id
                          AND id = :reservation_id
                          AND offering_version_id = :offering_version_id
                          AND status = 'confirmed'
                          AND revision = :reservation_revision
                        FOR UPDATE
                        """
                    ),
                    {
                        "organization_id": source.organization_id,
                        "reservation_id": source.reservation_id,
                        "offering_version_id": source.offering_version_id,
                        "reservation_revision": source.revision,
                    },
                )
            ).scalar_one_or_none()
            if not current:
                return None

            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.reservation_access
                               SET status = 'ready',
                                   revision = revision + 1
                             WHERE organization_id = :organization_id
                               AND id = :access_id
                               AND status = 'pending'
                               AND revision = :row_revision
                               AND reservation_revision = :reservation_revision
                               AND provisioned_at IS NOT NULL
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": source.organization_id,
                            "access_id": claim.id,
                            "row_revision": claim.revision,
                            "reservation_revision": source.revision,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                return _from_row(row)

            current = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.reservation_access
                            WHERE organization_id = :organization_id
                              AND id = :access_id
                            """
                        ),
                        {
                            "organization_id": source.organization_id,
                            "access_id": claim.id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if current is not None and current["status"] == "ready":
                return _from_row(current)
            return None

    async def list_unrevoked_for_reservation(
        self, organization_id: UUID, reservation_id: UUID
    ) -> tuple[ReservationAccess, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_read.reservation_access_v1
                            WHERE organization_id = :organization_id
                              AND reservation_id = :reservation_id
                              AND status <> 'revoked'
                            ORDER BY reservation_revision, access_key
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "reservation_id": reservation_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_from_row(row) for row in rows)

    async def mark_revoked_if_current(
        self,
        access: ReservationAccess,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess:
        async with tenant_transaction(self._session_factory, access.organization_id) as session:
            await self._lock_work_claim(session, work_claim)
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.reservation_access
                               SET status = 'revoked',
                                   revoked_at = clock_timestamp(),
                                   revision = revision + 1
                             WHERE organization_id = :organization_id
                               AND id = :access_id
                               AND status <> 'revoked'
                               AND revision = :row_revision
                            RETURNING *
                            """
                        ),
                        {
                            "organization_id": access.organization_id,
                            "access_id": access.id,
                            "row_revision": access.revision,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT *
                                FROM request_engine.reservation_access
                                WHERE organization_id = :organization_id
                                  AND id = :access_id
                                """
                            ),
                            {
                                "organization_id": access.organization_id,
                                "access_id": access.id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
        return _from_row(row)

    @staticmethod
    async def _lock_work_claim(session: AsyncSession, work_claim: DeliveryWorkClaim) -> None:
        locked = (
            await session.execute(
                text(
                    """
                    SELECT request_cmd.lock_outbox_message_claim(
                        :organization_id, :message_id, :claim_token
                    )
                    """
                ),
                {
                    "organization_id": work_claim.organization_id,
                    "message_id": work_claim.message_id,
                    "claim_token": work_claim.claim_token,
                },
            )
        ).scalar_one()
        if not locked:
            raise LeaseLostWorkError("delivery_outbox_authoritative_fence_lost")


def _from_row(row: RowMapping) -> ReservationAccess:
    return ReservationAccess(
        id=cast(UUID, row["id"]),
        organization_id=cast(UUID, row["organization_id"]),
        reservation_id=cast(UUID, row["reservation_id"]),
        reservation_revision=cast(int, row["reservation_revision"]),
        access_key=cast(str, row["access_key"]),
        kind=AccessKind(cast(str, row["kind"])),
        provider_key=cast(str | None, row["provider_key"]),
        materialization_key=cast(str, row["materialization_key"]),
        status=AccessStatus(cast(str, row["status"])),
        access_uri=cast(str | None, row["access_uri"]),
        external_ref=cast(str | None, row["external_ref"]),
        public_data=dict(cast(dict[str, object], row["public_data"])),
        provisioned_at=cast(datetime | None, row["provisioned_at"]),
        revoked_at=cast(datetime | None, row["revoked_at"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )
