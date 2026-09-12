"""The readiness projection reveals one boolean, without widening auth access."""

from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [("native", "active", True), ("native", "disabled", False), ("oidc", "active", False)],
)
async def test_native_authority_probe_has_no_mutation_or_provider_fallback(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    kind: str,
    status: str,
    expected: bool,
) -> None:
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities "
        "(id, kind, status, issuer_or_environment, configuration_ref) VALUES (%s, %s, %s, %s, %s)",
        (authority_id, kind, status, f"probe-{authority_id}", "private-provider-configuration"),
    )
    before = admin_conn.execute(
        "SELECT * FROM request_engine.identity_authorities WHERE id = %s", (authority_id,)
    ).fetchone()
    async with command_session_factory() as session, session.begin():
        for target, result in ((authority_id, expected), (uuid4(), False), (None, False)):
            assert (
                await session.scalar(
                    text("SELECT request_auth.is_native_authority_ready(:id)"), {"id": target}
                )
                is result
            )
    assert (
        admin_conn.execute(
            "SELECT * FROM request_engine.identity_authorities WHERE id = %s", (authority_id,)
        ).fetchone()
        == before
    )


def test_native_authority_probe_is_a_narrow_read_only_definer(admin_conn: Connection[Any]) -> None:
    signature = "request_auth.is_native_authority_ready(uuid)"
    row = admin_conn.execute(
        """
        SELECT p.prosecdef, p.provolatile, p.prorettype = 'boolean'::regtype,
               pg_get_userbyid(p.proowner), p.proconfig,
               has_function_privilege('request_engine_app', p.oid, 'EXECUTE'),
               has_function_privilege('request_engine_worker', p.oid, 'EXECUTE'),
               EXISTS (SELECT 1 FROM aclexplode(p.proacl) a
                        WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'),
               has_table_privilege('request_engine_app',
                                  'request_engine.identity_authorities', 'SELECT')
          FROM pg_proc p WHERE p.oid = %s::regprocedure
        """,
        (signature,),
    ).fetchone()
    assert row == (
        True,
        "s",
        True,
        "request_engine_schema_owner",
        ["search_path=pg_catalog, request_engine, pg_temp"],
        True,
        False,
        False,
        False,
    )
