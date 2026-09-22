"""Governed platform configuration command/read proofs for P7-B."""

from __future__ import annotations

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

P7_CAPABILITIES = frozenset(
    {
        "platform.configuration.read",
        "platform.configuration.stage",
        "platform.configuration.validate",
        "platform.configuration.activate",
        "platform.configuration.disable",
        "platform.secret.write",
        "platform.secret.rotate",
        "platform.secret.revoke",
        "platform.provider.test",
        "platform.readiness.read",
    }
)


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
        (actor_id, f"p7-test:{actor_id}"),
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
            (actor_id, capability, f"p7-test:{capability}"),
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


def _stage(
    conn: PgConnection,
    *,
    key: str,
    intent: str,
    kind: str = "email.delivery",
) -> tuple[UUID, int, str]:
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
            kind,
            '{"host":"mail.example.test","port":587,"security":"starttls"}',
            key,
            intent,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), int(row[1]), str(row[2])


def _validate(
    conn: PgConnection,
    revision: int,
    *,
    key: str,
    intent: str,
    kind: str = "email.delivery",
) -> tuple[UUID, int, str]:
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
        (kind, revision, key, intent),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), int(row[1]), str(row[2])


def _activate(
    conn: PgConnection,
    revision: int,
    *,
    expected_active_revision: int | None,
    key: str,
    intent: str,
    kind: str = "email.delivery",
) -> tuple[UUID, int, str]:
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
        (
            kind,
            revision,
            expected_active_revision,
            key,
            intent,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), int(row[1]), str(row[2])


def test_platform_owner_v3_contains_exact_p7_capability_delta(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT item ->> 'capability_key'
          FROM request_engine.platform_owner_policies AS policy,
               LATERAL jsonb_array_elements(policy.grants) AS item
         WHERE policy.policy_key = 'platform-owner-v3'
        """
    ).fetchall()
    keys = {str(row[0]) for row in rows}
    assert keys >= P7_CAPABILITIES

    previous = admin_conn.execute(
        """
        SELECT item ->> 'capability_key'
          FROM request_engine.platform_owner_policies AS policy,
               LATERAL jsonb_array_elements(policy.grants) AS item
         WHERE policy.policy_key = 'platform-owner-v2'
        """
    ).fetchall()
    previous_keys = {str(row[0]) for row in previous}
    assert P7_CAPABILITIES.isdisjoint(previous_keys)


def test_new_platform_owner_authority_adopts_v3_without_mutating_v2(
    admin_conn: PgConnection,
) -> None:
    owner_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            id,
            principal_plane,
            principal_kind,
            external_subject
        ) VALUES (%s, 'platform', 'human', %s)
        """,
        (owner_id, f"p7-owner:{owner_id}"),
    )
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
        ) VALUES (
            %s,
            'platform',
            'platform',
            'platform.owner.manage_lifecycle',
            false,
            'trust_bootstrap',
            'p7-owner-test'
        )
        """,
        (owner_id,),
    )

    rows = admin_conn.execute(
        """
        SELECT capability_key
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s
           AND status = 'active'
        """,
        (owner_id,),
    ).fetchall()
    granted = {str(row[0]) for row in rows}
    assert granted >= P7_CAPABILITIES

    revision = admin_conn.execute(
        """
        SELECT revision, grants
          FROM request_engine.platform_owner_policies
         WHERE policy_key = 'platform-owner-v2'
        """
    ).fetchone()
    assert revision is not None
    assert int(revision[0]) == 2


def test_configuration_lifecycle_replay_and_stale_activation_are_deterministic(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_platform_actor(
        admin_conn,
        {
            "platform.configuration.read",
            "platform.configuration.stage",
            "platform.configuration.validate",
            "platform.configuration.activate",
            "platform.configuration.disable",
        },
    )
    conn = _authenticated_control(
        platform_control_conn_factory,
        actor_id,
        authority_revision,
    )

    first = _stage(conn, key="a" * 64, intent="b" * 64)
    assert first[1:] == (1, "draft")
    assert _stage(conn, key="a" * 64, intent="b" * 64) == first

    with pytest.raises(psycopg.Error) as conflict:
        _stage(conn, key="a" * 64, intent="c" * 64)
    assert conflict.value.sqlstate == "23505"

    assert _validate(conn, 1, key="c" * 64, intent="d" * 64)[2] == "validated"
    assert (
        _activate(
            conn,
            1,
            expected_active_revision=None,
            key="e" * 64,
            intent="f" * 64,
        )[2]
        == "active"
    )

    second = _stage(conn, key="1" * 64, intent="2" * 64)
    assert second[1:] == (2, "draft")
    _validate(conn, 2, key="3" * 64, intent="4" * 64)
    _activate(
        conn,
        2,
        expected_active_revision=1,
        key="5" * 64,
        intent="6" * 64,
    )

    third = _stage(conn, key="7" * 64, intent="8" * 64)
    assert third[1] == 3
    _validate(conn, 3, key="9" * 64, intent="0" * 64)

    with pytest.raises(psycopg.Error) as stale:
        _activate(
            conn,
            3,
            expected_active_revision=1,
            key="a1" * 32,
            intent="b1" * 32,
        )
    assert stale.value.sqlstate == "40001"

    states = admin_conn.execute(
        """
        SELECT revision, state
          FROM request_engine.platform_configuration_revisions
         WHERE configuration_kind = 'email.delivery'
         ORDER BY revision
        """
    ).fetchall()
    assert states == [(1, "superseded"), (2, "active"), (3, "validated")]

    active_count = admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.platform_configuration_revisions
         WHERE configuration_kind = 'email.delivery'
           AND state = 'active'
        """
    ).fetchone()
    assert active_count == (1,)


def test_concurrent_first_activation_has_one_winner_and_one_stale_conflict(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_platform_actor(
        admin_conn,
        {
            "platform.configuration.stage",
            "platform.configuration.validate",
            "platform.configuration.activate",
        },
    )
    setup = _authenticated_control(
        platform_control_conn_factory,
        actor_id,
        authority_revision,
    )
    _stage(setup, key="1" * 64, intent="2" * 64)
    _stage(setup, key="3" * 64, intent="4" * 64)
    _validate(setup, 1, key="5" * 64, intent="6" * 64)
    _validate(setup, 2, key="7" * 64, intent="8" * 64)

    barrier = Barrier(2)

    def activate(revision: int, key: str, intent: str) -> str:
        conn = _authenticated_control(
            platform_control_conn_factory,
            actor_id,
            authority_revision,
        )
        barrier.wait(timeout=5)
        try:
            _activate(
                conn,
                revision,
                expected_active_revision=None,
                key=key,
                intent=intent,
            )
        except psycopg.Error as exc:
            return str(exc.sqlstate)
        return "success"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(activate, 1, "9" * 64, "a" * 64),
            pool.submit(activate, 2, "b" * 64, "c" * 64),
        )
        results = [future.result() for future in futures]

    assert sorted(results) == ["40001", "success"]
    active = admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.platform_configuration_revisions
         WHERE configuration_kind = 'email.delivery'
           AND state = 'active'
        """
    ).fetchone()
    assert active == (1,)


def test_secret_mutation_ledger_is_version_fenced_replayable_and_metadata_only(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
    platform_read_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_platform_actor(
        admin_conn,
        {
            "platform.configuration.read",
            "platform.secret.write",
            "platform.secret.rotate",
            "platform.secret.revoke",
        },
    )
    conn = _authenticated_control(
        platform_control_conn_factory,
        actor_id,
        authority_revision,
    )

    created_prepare = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'create',
              'email.smtp.password',
              'openbao',
              NULL,
              NULL,
              NULL,
              %s,
              %s
          )
        """,
        ("1" * 64, "2" * 64),
    ).fetchone()
    assert created_prepare is not None
    create_operation_id = UUID(str(created_prepare[0]))
    secret_id = UUID(str(created_prepare[3]))
    assert created_prepare[9] == "prepared"

    created_applied = conn.execute(
        """
        SELECT *
          FROM request_platform.mark_platform_secret_backend_applied(%s, 1)
        """,
        (create_operation_id,),
    ).fetchone()
    assert created_applied is not None
    assert created_applied[8:10] == (1, "backend_applied")

    created = conn.execute(
        "SELECT * FROM request_platform.commit_platform_secret_mutation(%s)",
        (create_operation_id,),
    ).fetchone()
    assert created is not None
    assert created[9] == "committed"
    binding_id = UUID(str(created[10]))
    assert created[11:13] == (1, "active")

    replay = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'create',
              'email.smtp.password',
              'openbao',
              NULL,
              NULL,
              NULL,
              %s,
              %s
          )
        """,
        ("1" * 64, "2" * 64),
    ).fetchone()
    assert replay is not None
    assert UUID(str(replay[0])) == create_operation_id
    assert replay[9] == "committed"

    read_conn = _authenticated_control(
        platform_read_conn_factory,
        actor_id,
        authority_revision,
    )
    cursor = read_conn.execute(
        "SELECT * FROM request_platform.read_platform_secret_binding(%s)",
        (binding_id,),
    )
    metadata = cursor.fetchone()
    assert metadata is not None
    assert cursor.description is not None
    column_names = [description.name for description in cursor.description]
    assert "secret_id" not in column_names
    assert metadata[0] == binding_id
    assert metadata[1:5] == ("email.smtp.password", "openbao", 1, "active")

    rotate_prepare = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'rotate',
              NULL,
              NULL,
              %s,
              1,
              1,
              %s,
              %s
          )
        """,
        (binding_id, "3" * 64, "4" * 64),
    ).fetchone()
    assert rotate_prepare is not None
    rotate_operation_id = UUID(str(rotate_prepare[0]))
    conn.execute(
        "SELECT * FROM request_platform.mark_platform_secret_backend_applied(%s, 2)",
        (rotate_operation_id,),
    ).fetchone()
    rotated = conn.execute(
        "SELECT * FROM request_platform.commit_platform_secret_mutation(%s)",
        (rotate_operation_id,),
    ).fetchone()
    assert rotated is not None
    assert rotated[8:13] == (2, "committed", binding_id, 2, "active")

    with pytest.raises(psycopg.Error) as stale:
        conn.execute(
            """
            SELECT *
              FROM request_platform.prepare_platform_secret_mutation(
                  'rotate',
                  NULL,
                  NULL,
                  %s,
                  1,
                  1,
                  %s,
                  %s
              )
            """,
            (binding_id, "5" * 64, "6" * 64),
        ).fetchone()
    assert stale.value.sqlstate == "40001"

    revoke_prepare = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'revoke',
              NULL,
              NULL,
              %s,
              2,
              2,
              %s,
              %s
          )
        """,
        (binding_id, "7" * 64, "8" * 64),
    ).fetchone()
    assert revoke_prepare is not None
    revoke_operation_id = UUID(str(revoke_prepare[0]))
    conn.execute(
        "SELECT * FROM request_platform.mark_platform_secret_backend_applied(%s, 2)",
        (revoke_operation_id,),
    ).fetchone()
    revoked = conn.execute(
        "SELECT * FROM request_platform.commit_platform_secret_mutation(%s)",
        (revoke_operation_id,),
    ).fetchone()
    assert revoked is not None
    assert revoked[8:13] == (2, "committed", binding_id, 3, "revoked")

    stored = admin_conn.execute(
        """
        SELECT secret_id, status, revision
          FROM request_engine.platform_secret_bindings
         WHERE id = %s
        """,
        (binding_id,),
    ).fetchone()
    assert stored == (secret_id, "revoked", 3)

    plaintext_columns = admin_conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'request_engine'
           AND table_name = 'platform_secret_mutations'
        """
    ).fetchall()
    assert {"value", "secret", "password"}.isdisjoint(
        {str(row[0]).lower() for row in plaintext_columns}
    )


def test_backend_applied_then_metadata_cas_loss_persists_reconciliation_state(
    admin_conn: PgConnection,
    platform_control_conn_factory: Callable[[], PgConnection],
) -> None:
    actor_id, authority_revision = _create_platform_actor(
        admin_conn,
        {"platform.secret.write", "platform.secret.rotate"},
    )
    conn = _authenticated_control(
        platform_control_conn_factory,
        actor_id,
        authority_revision,
    )

    prepared = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'create',
              'email.smtp.password',
              'openbao',
              NULL,
              NULL,
              NULL,
              %s,
              %s
          )
        """,
        ("a" * 64, "b" * 64),
    ).fetchone()
    assert prepared is not None
    create_operation_id = UUID(str(prepared[0]))
    conn.execute(
        "SELECT * FROM request_platform.mark_platform_secret_backend_applied(%s, 1)",
        (create_operation_id,),
    ).fetchone()
    created = conn.execute(
        "SELECT * FROM request_platform.commit_platform_secret_mutation(%s)",
        (create_operation_id,),
    ).fetchone()
    assert created is not None
    binding_id = UUID(str(created[10]))

    rotate = conn.execute(
        """
        SELECT *
          FROM request_platform.prepare_platform_secret_mutation(
              'rotate',
              NULL,
              NULL,
              %s,
              1,
              1,
              %s,
              %s
          )
        """,
        (binding_id, "c" * 64, "d" * 64),
    ).fetchone()
    assert rotate is not None
    operation_id = UUID(str(rotate[0]))
    conn.execute(
        "SELECT * FROM request_platform.mark_platform_secret_backend_applied(%s, 2)",
        (operation_id,),
    ).fetchone()

    admin_conn.execute(
        """
        UPDATE request_engine.platform_secret_bindings
           SET backend_version = 2,
               revision = 2,
               rotated_at = clock_timestamp()
         WHERE id = %s
        """,
        (binding_id,),
    )

    result = conn.execute(
        "SELECT * FROM request_platform.commit_platform_secret_mutation(%s)",
        (operation_id,),
    ).fetchone()
    assert result is not None
    assert result[9] == "reconcile_required"

    durable = admin_conn.execute(
        """
        SELECT state, applied_backend_version, reconcile_required_at
          FROM request_engine.platform_secret_mutations
         WHERE id = %s
        """,
        (operation_id,),
    ).fetchone()
    assert durable is not None
    assert durable[0:2] == ("reconcile_required", 2)
    assert durable[2] is not None


def test_platform_configuration_runtime_has_functions_but_no_direct_table_access(
    admin_conn: PgConnection,
) -> None:
    for table in (
        "platform_configuration_revisions",
        "platform_secret_bindings",
        "platform_configuration_facts",
        "platform_secret_mutations",
    ):
        privileges = admin_conn.execute(
            """
            SELECT
                has_table_privilege('request_platform_control', %s, 'SELECT'),
                has_table_privilege('request_platform_control', %s, 'INSERT'),
                has_table_privilege('request_platform_control', %s, 'UPDATE'),
                has_table_privilege('request_platform_control', %s, 'DELETE')
            """,
            (f"request_engine.{table}",) * 4,
        ).fetchone()
        assert privileges == (False, False, False, False)

    public_can_execute = admin_conn.execute(
        """
        SELECT has_function_privilege(
            'request_engine_app',
            'request_platform.stage_platform_configuration'
            '(text,text,jsonb,uuid,text,text)',
            'EXECUTE'
        )
        """
    ).fetchone()
    assert public_can_execute == (False,)

    runtime_can_execute = admin_conn.execute(
        """
        SELECT has_function_privilege(
            'request_platform_control',
            'request_platform.stage_platform_configuration'
            '(text,text,jsonb,uuid,text,text)',
            'EXECUTE'
        )
        """
    ).fetchone()
    assert runtime_can_execute == (True,)

    provider_validation_authority = admin_conn.execute(
        """
        SELECT
            has_function_privilege(
                'request_platform_control',
                'request_platform.validate_platform_configuration_provider'
                '(text,bigint,bigint,integer,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.resolve_platform_provider_secret(uuid,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.validate_platform_configuration'
                '(text,bigint,text,text)',
                'EXECUTE'
            )
        """
    ).fetchone()
    assert provider_validation_authority == (True, True, False)

    secret_mutation_authority = admin_conn.execute(
        """
        SELECT
            has_function_privilege(
                'request_platform_control',
                'request_platform.prepare_platform_secret_mutation'
                '(text,text,text,uuid,bigint,integer,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.mark_platform_secret_backend_applied(uuid,integer)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.commit_platform_secret_mutation(uuid)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.record_platform_secret_binding'
                '(text,text,uuid,integer,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.commit_platform_secret_rotation'
                '(uuid,bigint,integer,integer,text,text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.revoke_platform_secret_binding'
                '(uuid,bigint,integer,text,text)',
                'EXECUTE'
            )
        """
    ).fetchone()
    assert secret_mutation_authority == (True, True, True, False, False, False)

    control_read_authority = admin_conn.execute(
        """
        SELECT
            has_function_privilege(
                'request_platform_control',
                'request_platform.read_platform_configuration_revisions(text)',
                'EXECUTE'
            ),
            has_function_privilege(
                'request_platform_control',
                'request_platform.read_platform_secret_binding(uuid)',
                'EXECUTE'
            )
        """
    ).fetchone()
    assert control_read_authority == (False, False)

    helper_is_private = admin_conn.execute(
        """
        SELECT has_function_privilege(
            'request_platform_control',
            'request_platform.assert_platform_configuration_actor(text)',
            'EXECUTE'
        )
        """
    ).fetchone()
    assert helper_is_private == (False,)
