"""Real dedicated-role receipt append, conflict and orphan durability evidence."""

import runpy
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import Connection, Error, sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import text
from sqlalchemy.engine import URL

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    RetainedProofVersion,
    StagedRecoverySecret,
)
from request_engine.platform.secrets.durable_proof_inventory import DurableProofInventoryStore

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


@pytest_asyncio.fixture
async def recorder_sessions(
    admin_conn: Connection[Any], pg_conninfo: str
) -> AsyncIterator[SessionFactory]:
    role, password = f"proof_recorder_{uuid4().hex[:12]}", uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER PASSWORD {} "
            "IN ROLE request_retention_recorder"
        ).format(sql.Identifier(role), sql.Literal(password))
    )
    values = conninfo_to_dict(pg_conninfo)
    engine = create_postgres_engine(
        URL.create(
            "postgresql+asyncpg",
            username=role,
            password=password,
            host=str(values["host"]),
            port=int(str(values["port"])),
            database=str(values["dbname"]),
        ).render_as_string(hide_password=False)
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


class RetainedStore:
    def __init__(self, staged: StagedRecoverySecret) -> None:
        self.staged = staged
        self.stage_calls = 0

    async def stage(
        self, *, case_id: object, generation: int, secret: str, expires_at: datetime
    ) -> StagedRecoverySecret:
        self.stage_calls += 1
        return self.staged

    async def discard(self, *, case_id: object, generation: int) -> None:
        pytest.fail("a recorder failure must not destroy a shared retained winner")

    async def read(self, *, reference: str) -> str:
        pytest.fail("inventory never reads plaintext")


@pytest.mark.asyncio
async def test_recorder_persists_retained_expiry_and_replays_without_mutation(
    admin_conn: Connection[Any],
    recorder_sessions: SessionFactory,
) -> None:
    now, case, backend = datetime.now(UTC), uuid4(), uuid4()
    expiry = now + timedelta(minutes=10)
    staged = StagedRecoverySecret(
        f"request-engine/identity-recovery/{case}/1",
        "a" * 64,
        expiry,
        False,
        RetainedProofVersion(1, now, expiry - timedelta(seconds=2)),
    )
    provider = RetainedStore(staged)
    store = DurableProofInventoryStore(
        provider, recorder_sessions, backend_id=backend, mount="secret"
    )
    for _ in range(2):
        assert (
            await store.stage(
                case_id=case,
                generation=1,
                secret="losing-candidate",
                expires_at=expiry + timedelta(days=1),
            )
            == staged
        )
    row = admin_conn.execute(
        "SELECT expires_at,version FROM request_engine.temporary_proof_retention_receipts"
    ).fetchall()
    assert row == [(expiry, 1)]
    # A later caller/business failure cannot roll back the separately committed receipt.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.temporary_proof_retention_receipts"
    ).fetchone() == (1,)
    provider.staged = StagedRecoverySecret(
        staged.reference,
        staged.digest,
        expiry + timedelta(minutes=1),
        False,
        staged.retention_version,
    )
    with pytest.raises(RecoveryDeliveryRetryable):
        await store.stage(
            case_id=case, generation=1, secret="loser", expires_at=expiry + timedelta(days=1)
        )
    assert admin_conn.execute(
        "SELECT expires_at FROM request_engine.temporary_proof_retention_receipts"
    ).fetchone() == (expiry,)
    for mutation in (
        "UPDATE request_engine.temporary_proof_retention_receipts "
        "SET expires_at=expires_at+interval '1 minute'",
        "DELETE FROM request_engine.temporary_proof_retention_receipts",
    ):
        with pytest.raises(Error) as denied:
            admin_conn.execute(mutation)
        assert denied.value.sqlstate == "55000"


def test_app_and_recorder_cannot_read_or_write_inventory_tables(
    admin_conn: Connection[Any],
) -> None:
    for role in ("request_engine_app", "request_retention_recorder"):
        admin_conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        try:
            with pytest.raises(Error) as denied:
                admin_conn.execute(
                    "SELECT * FROM request_engine.temporary_proof_retention_receipts"
                )
            assert denied.value.sqlstate == "42501"
        finally:
            admin_conn.execute("RESET ROLE")
        assert admin_conn.execute(
            "SELECT has_table_privilege(%s,"
            "'request_engine.temporary_proof_retention_receipts','INSERT'),"
            "has_table_privilege(%s,'request_engine.temporary_proof_retention_receipts','UPDATE'),"
            "has_table_privilege(%s,'request_engine.temporary_proof_retention_receipts','DELETE')",
            (role, role, role),
        ).fetchone() == (False, False, False)
    admin_conn.execute("SET ROLE request_engine_app")
    try:
        with pytest.raises(Error) as denied:
            admin_conn.execute(
                "SELECT request_cmd.record_temporary_proof_retention("
                "NULL,NULL,NULL,NULL,NULL,NULL,NULL)"
            )
        assert denied.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")


@pytest.mark.parametrize(
    "unsafe_change",
    [
        "ALTER ROLE request_retention_recorder LOGIN",
        "ALTER ROLE request_retention_recorder BYPASSRLS",
        "ALTER ROLE request_retention_recorder SET statement_timeout='5s'",
        "GRANT USAGE ON SCHEMA request_read TO request_retention_recorder",
        "GRANT SELECT ON request_engine.native_identities TO request_retention_recorder",
        "CREATE ROLE request_retention_unreviewed NOLOGIN",
    ],
)
def test_current_retention_role_inventory_rejects_escalation(
    admin_conn: Connection[Any], unsafe_change: LiteralString
) -> None:
    migration = Path(__file__).resolve().parents[2] / (
        "migrations/versions/0020_retention_recorder_role_contract.py"
    )
    # Trusted repository migration text, never user-provided SQL.
    inventory = sql.SQL(cast(LiteralString, runpy.run_path(str(migration))["ROLE_INVENTORY_SQL"]))
    admin_conn.execute(inventory)
    # Role/catalog changes are transactional, including privileges. Each defect
    # must abort and roll back; the actual canonical group is never left elevated.
    with pytest.raises(Error, match="Retention recorder"), admin_conn.transaction():
        admin_conn.execute(unsafe_change)
        admin_conn.execute(inventory)
    admin_conn.execute(inventory)


@pytest.mark.asyncio
async def test_wrong_database_role_rejected_before_provider_staging(
    command_session_factory: SessionFactory,
) -> None:
    now, case = datetime.now(UTC), uuid4()
    provider = RetainedStore(
        StagedRecoverySecret(
            f"request-engine/identity-recovery/{case}/1",
            "a" * 64,
            now + timedelta(minutes=10),
            True,
        )
    )
    store = DurableProofInventoryStore(
        provider,
        command_session_factory,
        backend_id=uuid4(),
        mount="secret",
    )
    with pytest.raises(RecoveryDeliveryPermanent, match="role is not isolated"):
        await store.stage(
            case_id=case,
            generation=1,
            secret="must-not-be-staged",
            expires_at=now + timedelta(minutes=10),
        )
    assert provider.stage_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_role",
    [
        "request_engine_app",
        "request_platform_control_definer",
        "request_bootstrap_definer",
    ],
)
async def test_recorder_set_role_authority_is_rejected_even_without_inheritance(
    admin_conn: Connection[Any],
    recorder_sessions: SessionFactory,
    extra_role: str,
) -> None:
    async with recorder_sessions() as session:
        login = str((await session.execute(text("SELECT current_user"))).scalar_one())
    admin_conn.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
            sql.Identifier(extra_role),
            sql.Identifier(login),
        )
    )
    now, case = datetime.now(UTC), uuid4()
    provider = RetainedStore(
        StagedRecoverySecret(
            f"request-engine/identity-recovery/{case}/1",
            "a" * 64,
            now + timedelta(minutes=10),
            True,
        )
    )
    store = DurableProofInventoryStore(
        provider,
        recorder_sessions,
        backend_id=uuid4(),
        mount="secret",
    )
    with pytest.raises(RecoveryDeliveryPermanent, match="role is not isolated"):
        await store.stage(
            case_id=case,
            generation=1,
            secret="must-not-be-staged",
            expires_at=now + timedelta(minutes=10),
        )
    assert provider.stage_calls == 0
