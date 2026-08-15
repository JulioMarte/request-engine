import json
import os
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection, sql
from psycopg.errors import InsufficientPrivilege

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]


def _pg_values() -> tuple[str, str, str, str, str]:
    return (
        os.environ.get("PGHOST", "127.0.0.1"),
        os.environ.get("PGPORT", "5432"),
        os.environ.get("PGDATABASE", "request_engine_v3"),
        os.environ.get("PGUSER", "request_engine"),
        os.environ.get("PGPASSWORD", "request_engine"),
    )


class _ActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer e2e":
            raise AuthenticationRequired
        return self._actor


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_real_app_login_serves_tenant_scoped_business_over_http_and_cannot_escalate() -> None:
    host, port, database, admin_user, admin_password = _pg_values()
    admin: PgConnection = psycopg.connect(
        (
            f"host={host} port={port} dbname={database} "
            f"user={admin_user} password={admin_password}"
        ),
        autocommit=True,
    )
    role_name = f"request_engine_app_e2e_{uuid4().hex[:16]}"
    role_password = uuid4().hex
    suffix = uuid4().hex
    location_key = f"e2e-office-{suffix}"
    organization_id: UUID | None = None
    role_created = False

    try:
        organization_row = admin.execute(
            """
            INSERT INTO request_engine.organizations (
                organization_key, display_name, public_profile
            ) VALUES (%s, 'E2E Clinic', %s::jsonb)
            RETURNING id
            """,
            (f"e2e-{suffix}", json.dumps({"summary": "runtime login proof"})),
        ).fetchone()
        assert organization_row is not None
        organization_id = UUID(str(organization_row[0]))

        principal_row = admin.execute(
            """
            INSERT INTO request_engine.principals (
                organization_id, principal_kind, external_subject
            ) VALUES (%s, 'agent', %s)
            RETURNING id
            """,
            (organization_id, f"e2e-agent-{suffix}"),
        ).fetchone()
        assert principal_row is not None
        principal_id = UUID(str(principal_row[0]))

        admin.execute(
            """
            INSERT INTO request_engine.locations (
                organization_id, location_key, display_name, timezone, public_data
            ) VALUES (%s, %s, 'E2E Office', 'America/Santo_Domingo', %s::jsonb)
            """,
            (
                organization_id,
                location_key,
                json.dumps({"address": "Puerto Plata"}),
            ),
        )

        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(sql.Identifier(role_name), sql.Literal(role_password))
        )
        role_created = True
        admin.execute(
            sql.SQL("GRANT request_engine_app TO {} WITH INHERIT TRUE").format(
                sql.Identifier(role_name)
            )
        )

        engine = create_postgres_engine(
            f"postgresql+asyncpg://{role_name}:{role_password}@{host}:{port}/{database}"
        )
        try:
            session_factory = create_session_factory(engine)
            actor = ActorContext(
                organization_id=organization_id,
                principal_id=principal_id,
                capabilities=frozenset({"business.read"}),
            )
            app = create_app(
                session_factory=session_factory,
                actor_resolver=_ActorResolver(actor),
                appointment_option_signing_key=b"phase6-e2e-runtime-login-signing-key",
            )

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/v1/business",
                    headers={"Authorization": "Bearer e2e"},
                )

            assert response.status_code == 200
            payload = response.json()
            assert payload["organization_id"] == str(organization_id)
            assert payload["organization_key"] == f"e2e-{suffix}"
            assert payload["display_name"] == "E2E Clinic"
            assert payload["public_profile"] == {"summary": "runtime login proof"}
            assert len(payload["locations"]) == 1
            location = payload["locations"][0]
            assert UUID(location["id"])
            assert location["location_key"] == location_key
            assert location["display_name"] == "E2E Office"
            assert location["timezone"] == "America/Santo_Domingo"
            assert location["public_data"] == {"address": "Puerto Plata"}
            assert UUID(response.headers["X-Correlation-ID"])
        finally:
            await engine.dispose()

        login: PgConnection = psycopg.connect(
            (
                f"host={host} port={port} dbname={database} "
                f"user={role_name} password={role_password}"
            ),
            autocommit=True,
        )
        try:
            identity = login.execute(
                """
                SELECT current_user = session_user,
                       pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                       pg_has_role(current_user, 'request_engine_worker', 'MEMBER'),
                       pg_has_role(current_user, 'request_engine_admin', 'MEMBER')
                """
            ).fetchone()
            assert identity == (True, True, False, False)
            for forbidden_role in (
                "request_engine_worker",
                "request_engine_admin",
                "request_engine_schema_owner",
            ):
                with pytest.raises(InsufficientPrivilege):
                    login.execute(
                        sql.SQL("SET ROLE {}").format(sql.Identifier(forbidden_role))
                    )
        finally:
            login.close()
    finally:
        if role_created:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        if organization_id is not None:
            admin.execute(
                "DELETE FROM request_engine.locations WHERE organization_id = %s",
                (organization_id,),
            )
            admin.execute(
                "DELETE FROM request_engine.principals WHERE organization_id = %s",
                (organization_id,),
            )
            admin.execute(
                "DELETE FROM request_engine.organizations WHERE id = %s",
                (organization_id,),
            )
        admin.close()
