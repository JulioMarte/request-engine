"""Active-runtime configuration resolver poll-convergence proof for P7-F.

The resolver must converge on the PostgreSQL ACTIVE revision even when no
LISTEN/NOTIFY invalidation reaches the process. This proof isolates the polling
backstop: ``invalidate`` is never called, yet the resolver adopts a newly
activated revision once the bounded cache interval elapses, and still serves the
cached revision inside that interval.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.platform_configuration.adapters.db.runtime import (
    PostgresActivePlatformConfigurationSource,
)
from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfigurationResolver,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_KIND = "email.delivery"


def _create_platform_actor(
    admin_conn: PgConnection,
    capabilities: Iterable[str],
) -> tuple[UUID, int]:
    actor_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            id,
            principal_plane,
            principal_kind,
            external_subject
        ) VALUES (%s, 'platform', 'human', %s)
        """,
        (actor_id, f"p7-hot-reload:{actor_id}"),
    )
    for capability in capabilities:
        admin_conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                provenance_kind,
                provenance_reference
            ) VALUES (%s, 'platform', 'platform', %s, false, 'trust_bootstrap', %s)
            """,
            (actor_id, capability, f"p7-hot-reload:{capability}"),
        )
    row = admin_conn.execute(
        """
        SELECT authority_revision
          FROM request_engine.principals
         WHERE id = %s
        """,
        (actor_id,),
    ).fetchone()
    assert row is not None
    return actor_id, int(row[0])


def _authenticated_control(
    factory: Callable[[], PgConnection],
    actor_id: UUID,
    authority_revision: int,
) -> PgConnection:
    conn = factory()
    conn.autocommit = True
    settings = {
        "request_engine.authenticated_principal_id": str(actor_id),
        "request_engine.authority_revision": str(authority_revision),
        "request_engine.authentication_method": "webauthn",
        "request_engine.correlation_id": str(uuid4()),
    }
    for key, value in settings.items():
        conn.execute("SELECT set_config(%s, %s, false)", (key, value))
    return conn


def _stage(conn: PgConnection, *, host: str, key: str, intent: str) -> int:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.stage_platform_configuration(
              %s,
              'smtp',
              %s::jsonb,
              NULL,
              %s,
              %s
          )
        """,
        (
            _KIND,
            f'{{"host":"{host}","port":587,"sender":"resolver@example.test","security":"starttls"}}',
            key,
            intent,
        ),
    ).fetchone()
    assert row is not None
    return int(row[1])


def _validate(conn: PgConnection, revision: int, *, key: str, intent: str) -> None:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.validate_platform_configuration_provider(
              %s,
              %s,
              NULL,
              NULL,
              %s,
              %s
          )
        """,
        (_KIND, revision, key, intent),
    ).fetchone()
    assert row is not None
    assert str(row[2]) == "validated"


def _activate(
    conn: PgConnection,
    revision: int,
    *,
    expected_active_revision: int | None,
    key: str,
    intent: str,
) -> None:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.activate_platform_configuration(
              %s,
              %s,
              %s,
              %s,
              %s
          )
        """,
        (_KIND, revision, expected_active_revision, key, intent),
    ).fetchone()
    assert row is not None
    assert str(row[2]) == "active"


async def test_active_runtime_resolver_converges_by_polling_without_notification(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
    platform_control_session_factory: SessionFactory,
) -> None:
    actor_id, authority_revision = _create_platform_actor(
        admin_conn,
        {
            "platform.configuration.stage",
            "platform.configuration.validate",
            "platform.configuration.activate",
        },
    )
    conn = _authenticated_control(
        platform_control_conn_factory,
        actor_id,
        authority_revision,
    )

    first_revision = _stage(conn, host="smtp-one.example.test", key="h" * 64, intent="1" * 64)
    _validate(conn, first_revision, key="i" * 64, intent="1" * 64)
    _activate(
        conn,
        first_revision,
        expected_active_revision=None,
        key="j" * 64,
        intent="1" * 64,
    )

    resolver = ActivePlatformConfigurationResolver(
        source=PostgresActivePlatformConfigurationSource(platform_control_session_factory),
        secret_store=None,
        poll_interval_seconds=1.0,
    )

    cached_first = await resolver.resolve_smtp()
    assert cached_first is not None
    assert cached_first.active_revision == first_revision
    assert cached_first.configuration.host == "smtp-one.example.test"

    second_revision = _stage(conn, host="smtp-two.example.test", key="k" * 64, intent="2" * 64)
    _validate(conn, second_revision, key="l" * 64, intent="2" * 64)
    _activate(
        conn,
        second_revision,
        expected_active_revision=first_revision,
        key="m" * 64,
        intent="2" * 64,
    )

    # No invalidate() and therefore no NOTIFY: inside the cache interval the
    # resolver still serves the previous ACTIVE revision.
    still_cached = await resolver.resolve_smtp()
    assert still_cached is not None
    assert still_cached.active_revision == first_revision

    await asyncio.sleep(1.5)

    adopted = await resolver.resolve_smtp()
    assert adopted is not None
    assert adopted.active_revision == second_revision
    assert adopted.configuration.host == "smtp-two.example.test"
