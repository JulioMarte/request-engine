"""Managed OIDC projection invariants for P7-H.

The governed platform configuration revision is authoritative.  The
identity_authorities row is only the stable-id runtime projection consumed by
existing IdentityBinding rows.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
]


def _create_actor(admin_conn: PgConnection, capabilities: Iterable[str]) -> tuple[UUID, int]:
    actor_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            id, principal_plane, principal_kind, external_subject
        ) VALUES (%s, 'platform', 'human', %s)
        """,
        (actor_id, f"p7-oidc:{actor_id}"),
    )
    for capability in capabilities:
        admin_conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            ) VALUES (%s, 'platform', 'platform', %s, false, 'trust_bootstrap', %s)
            """,
            (actor_id, capability, f"p7-oidc:{capability}"),
        )
    row = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (actor_id,),
    ).fetchone()
    assert row is not None
    return actor_id, int(row[0])


def _control(
    factory: Callable[[], PgConnection],
    actor_id: UUID,
    authority_revision: int,
) -> PgConnection:
    conn = factory()
    conn.autocommit = True
    for key, value in {
        "request_engine.authenticated_principal_id": str(actor_id),
        "request_engine.authority_revision": str(authority_revision),
        "request_engine.authentication_method": "webauthn",
        "request_engine.correlation_id": str(uuid4()),
    }.items():
        conn.execute("SELECT set_config(%s, %s, false)", (key, value))
    return conn


def _stage_oidc(
    conn: PgConnection,
    revision_marker: str,
    *,
    issuer: str = "https://id.example.test",
) -> tuple[UUID, int, str]:
    configuration = json.dumps(
        {
            "issuer": issuer,
            "jwks_uri": f"https://id.example.test/{revision_marker}/jwks.json",
            "audience": f"request-engine-{revision_marker}",
        }
    )
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.stage_platform_configuration(
              'identity.oidc',
              'oidc',
              %s::jsonb,
              NULL,
              %s,
              %s
          )
        """,
        (configuration, revision_marker * 64, revision_marker.upper() * 64),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), int(row[1]), str(row[2])


def _validate(conn: PgConnection, revision: int, marker: str) -> None:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.validate_platform_configuration_provider(
              'identity.oidc', %s, NULL, NULL, %s, %s
          )
        """,
        (revision, marker * 64, marker.upper() * 64),
    ).fetchone()
    assert row is not None
    assert row[2] == "validated"


def _activate(
    conn: PgConnection,
    revision: int,
    *,
    expected_active_revision: int | None,
    marker: str,
) -> str:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.activate_platform_configuration(
              'identity.oidc', %s, %s, %s, %s
          )
        """,
        (
            revision,
            expected_active_revision,
            marker * 64,
            marker.upper() * 64,
        ),
    ).fetchone()
    assert row is not None
    return str(row[2])


def _disable(conn: PgConnection, revision: int, marker: str) -> str:
    row = conn.execute(
        """
        SELECT *
          FROM request_platform.disable_platform_configuration(
              'identity.oidc', %s, %s, %s
          )
        """,
        (revision, marker * 64, marker.upper() * 64),
    ).fetchone()
    assert row is not None
    return str(row[2])


def test_managed_oidc_projection_tracks_replace_and_disable(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_actor(
        admin_conn,
        {
            "platform.configuration.stage",
            "platform.configuration.validate",
            "platform.configuration.activate",
            "platform.configuration.disable",
        },
    )
    control = _control(platform_control_conn_factory, actor_id, authority_revision)

    assert _stage_oidc(control, "a")[1:] == (1, "draft")
    _validate(control, 1, "b")
    assert _activate(control, 1, expected_active_revision=None, marker="c") == "active"

    first = admin_conn.execute(
        """
        SELECT id, status, configuration_ref, revision
          FROM request_engine.identity_authorities
         WHERE kind = 'oidc' AND issuer_or_environment = 'https://id.example.test'
        """
    ).fetchone()
    assert first is not None
    authority_id = UUID(str(first[0]))
    assert first[1] == "active"
    first_ref = json.loads(str(first[2]))
    assert first_ref["managed_configuration_revision"] == 1
    assert first_ref["audience"] == "request-engine-a"

    assert _stage_oidc(control, "d")[1:] == (2, "draft")
    _validate(control, 2, "e")
    assert _activate(control, 2, expected_active_revision=1, marker="f") == "active"

    replacement = admin_conn.execute(
        """
        SELECT id, status, configuration_ref, revision
          FROM request_engine.identity_authorities
         WHERE kind = 'oidc' AND issuer_or_environment = 'https://id.example.test'
        """
    ).fetchone()
    assert replacement is not None
    assert UUID(str(replacement[0])) == authority_id
    assert replacement[1] == "active"
    replacement_ref = json.loads(str(replacement[2]))
    assert replacement_ref["managed_configuration_revision"] == 2
    assert replacement_ref["audience"] == "request-engine-d"
    assert int(replacement[3]) > int(first[3])

    states = admin_conn.execute(
        """
        SELECT revision, state
          FROM request_engine.platform_configuration_revisions
         WHERE configuration_kind = 'identity.oidc'
         ORDER BY revision
        """
    ).fetchall()
    assert states == [(1, "superseded"), (2, "active")]

    assert _disable(control, 2, "g") == "disabled"
    disabled = admin_conn.execute(
        """
        SELECT id, status
          FROM request_engine.identity_authorities
         WHERE kind = 'oidc' AND issuer_or_environment = 'https://id.example.test'
        """
    ).fetchone()
    assert disabled == (authority_id, "disabled")


def test_concurrent_managed_oidc_activation_projects_only_the_winner(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_actor(
        admin_conn,
        {
            "platform.configuration.stage",
            "platform.configuration.validate",
            "platform.configuration.activate",
        },
    )
    setup = _control(platform_control_conn_factory, actor_id, authority_revision)
    _stage_oidc(setup, "h")
    _stage_oidc(setup, "i")
    _validate(setup, 1, "j")
    _validate(setup, 2, "k")

    barrier = Barrier(2)

    def activate(revision: int, marker: str) -> str:
        conn = _control(platform_control_conn_factory, actor_id, authority_revision)
        barrier.wait(timeout=5)
        try:
            return _activate(
                conn,
                revision,
                expected_active_revision=None,
                marker=marker,
            )
        except psycopg.Error as exc:
            return str(exc.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(activate, 1, "l"),
            pool.submit(activate, 2, "m"),
        ]
        outcomes = [future.result() for future in results]

    assert sorted(outcomes) == ["40001", "active"]
    active = admin_conn.execute(
        """
        SELECT revision, configuration
          FROM request_engine.platform_configuration_revisions
         WHERE configuration_kind = 'identity.oidc' AND state = 'active'
        """
    ).fetchone()
    assert active is not None
    active_revision = int(active[0])

    projected = admin_conn.execute(
        """
        SELECT status, configuration_ref
          FROM request_engine.identity_authorities
         WHERE kind = 'oidc' AND issuer_or_environment = 'https://id.example.test'
        """
    ).fetchone()
    assert projected is not None
    assert projected[0] == "active"
    projected_ref = json.loads(str(projected[1]))
    assert int(projected_ref["managed_configuration_revision"]) == active_revision
