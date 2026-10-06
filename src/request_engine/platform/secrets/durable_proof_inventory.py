"""Dedicated technical receipt recording; no business reads or destroy authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    StagedRecoverySecret,
)
from request_engine.platform.secrets.delivery_parts import RecoverySecretStore
from request_engine.platform.secrets.kv_v2_retention import validate_temporary_reference


class DurableProofInventoryStore:
    """Stage outside owner locks, commit its retained receipt, then return to owner.

    Own transaction records even a proof whose later owner command fails. No
    destruction follows record failure: another issuer may retain the CAS winner.
    The separately configured session factory must be the retention-recorder role.
    """

    def __init__(
        self,
        store: RecoverySecretStore,
        sessions: SessionFactory,
        *,
        backend_id: UUID,
        mount: str,
    ) -> None:
        self._store, self._sessions = store, sessions
        self._backend_id, self._mount = backend_id, mount

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        # Configuration is not evidence of least privilege. Check the actual
        # connection before provider staging; no owner locks are held here.
        try:
            await self._assert_recorder_role()
        except (SQLAlchemyError, OSError):
            raise RecoveryDeliveryRetryable("retained proof recorder unavailable") from None
        staged = await self._store.stage(
            case_id=case_id,
            generation=generation,
            secret=secret,
            expires_at=expires_at,
        )
        retained = staged.retention_version
        if retained is None or retained.deletion_at > staged.expires_at:
            raise RecoveryDeliveryPermanent("retained proof inventory metadata unavailable")
        validate_temporary_reference(staged.reference, prefix="request-engine/identity-recovery")
        try:
            async with self._sessions() as session, session.begin():
                await session.execute(
                    text("""
                        SELECT request_cmd.record_temporary_proof_retention(
                            :backend,:mount,:reference,:version,:created,:deletion,:expiry)
                    """),
                    {
                        "backend": self._backend_id,
                        "mount": self._mount,
                        "reference": staged.reference,
                        "version": retained.version,
                        "created": retained.created_at,
                        "deletion": retained.deletion_at,
                        "expiry": staged.expires_at,
                    },
                )
        except (SQLAlchemyError, OSError):
            raise RecoveryDeliveryRetryable("retained proof inventory unavailable") from None
        return staged

    async def _assert_recorder_role(self) -> None:
        async with self._sessions() as session, session.begin():
            admitted = (
                await session.execute(
                    text("""
                SELECT NOT (self.rolsuper OR self.rolbypassrls OR self.rolcreatedb
                    OR self.rolcreaterole OR self.rolreplication)
                  AND pg_has_role(current_user,'request_retention_recorder','MEMBER')
                  AND NOT (recorder.rolcanlogin OR recorder.rolsuper OR recorder.rolbypassrls
                    OR recorder.rolcreatedb OR recorder.rolcreaterole OR recorder.rolreplication)
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member=recorder.oid
                       OR (m.member=self.oid AND (m.roleid<>recorder.oid OR m.admin_option))
                  )
                FROM pg_roles self
                JOIN pg_roles recorder ON recorder.rolname='request_retention_recorder'
                WHERE self.rolname=current_user
            """)
                )
            ).scalar_one()
        if admitted is not True:
            raise RecoveryDeliveryPermanent("retained proof recorder role is not isolated")

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        await self._store.discard(case_id=case_id, generation=generation)

    async def read(self, *, reference: str) -> str:
        return await self._store.read(reference=reference)
