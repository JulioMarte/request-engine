"""Governed native identity recovery: double control, issuance, delivery, revoke."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import insert_authority
from platform_provisioning_support import platform_grant, platform_principal, principal_revision
from psycopg import Connection, Error

from request_engine.modules.tenancy.adapters.db.identity_recovery_commands import (
    PostgresIdentityRecoveryCommands,
)
from request_engine.modules.tenancy.application.commands.identity_recovery import (
    IdentityRecoveryConflict,
    IdentityRecoveryRevisionConflict,
    IssueIdentityRecoveryCaseCommand,
)
from request_engine.modules.tenancy.application.queries.identity_recovery import (
    IdentityRecoveryCaseView,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import DeliveryOutcome, StagedRecoverySecret
from request_engine.platform.security.native_auth import hash_password, issue_opaque_token
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "replacement correct horse battery staple"

_CREATE: LiteralString = (
    "SELECT * FROM request_platform.create_identity_recovery_case("
    "CAST(%s AS uuid), CAST(%s AS uuid), CAST(%s AS text), CAST(%s AS text), "
    "CAST(%s AS text), CAST(%s AS text), CAST(%s AS text))"
)
_APPROVE: LiteralString = (
    "SELECT * FROM request_platform.approve_identity_recovery_case("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text), CAST(%s AS text), "
    "CAST(%s AS text))"
)
_PREPARE: LiteralString = (
    "SELECT * FROM request_platform.prepare_identity_recovery_issue("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text), CAST(%s AS text))"
)
_ISSUE: LiteralString = (
    "SELECT * FROM request_platform.issue_identity_recovery_case("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS integer), CAST(%s AS uuid), "
    "CAST(%s AS bytea), CAST(%s AS text), CAST(%s AS timestamptz), CAST(%s AS uuid), "
    "CAST(%s AS text), CAST(%s AS text), CAST(%s AS text), CAST(%s AS text))"
)
_REVOKE: LiteralString = (
    "SELECT * FROM request_platform.revoke_identity_recovery_case("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text), CAST(%s AS text), "
    "CAST(%s AS text))"
)
_CLAIM: LiteralString = (
    "SELECT * FROM request_platform.claim_identity_recovery_delivery_tickets("
    "CAST(%s AS integer), CAST(%s AS integer))"
)
_COMPLETE: LiteralString = (
    "SELECT request_platform.complete_identity_recovery_delivery_ticket("
    "CAST(%s AS uuid), CAST(%s AS uuid), CAST(%s AS text), CAST(%s AS text))"
)
_RETRY: LiteralString = (
    "SELECT request_platform.retry_identity_recovery_delivery_ticket("
    "CAST(%s AS uuid), CAST(%s AS uuid), CAST(%s AS integer), CAST(%s AS text))"
)
_RENEW: LiteralString = (
    "SELECT request_platform.renew_identity_recovery_delivery_ticket_lease("
    "CAST(%s AS uuid), CAST(%s AS uuid), CAST(%s AS integer))"
)
_CONSUME: LiteralString = (
    "SELECT request_auth.consume_native_recovery_intent("
    "CAST(%s AS uuid), CAST(%s AS bytea), CAST(%s AS uuid), CAST(%s AS text))"
)


def _digest() -> str:
    return hashlib.sha256(uuid4().hex.encode("utf-8")).hexdigest()


def _set_actor(conn: PgConnection, actor: UUID, *, revision: int | None = None) -> None:
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(actor),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(conn, actor) if revision is None else revision),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authentication_method', 'native_session', false)"
    )
    conn.execute(
        "SELECT set_config('request_engine.correlation_id', %s, false)",
        (str(uuid4()),),
    )


_ROLE_STATEMENTS: dict[str, LiteralString] = {
    "request_platform_control": "SET ROLE request_platform_control",
    "request_engine_worker": "SET ROLE request_engine_worker",
    "request_engine_app": "SET ROLE request_engine_app",
}


def _call(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
    *,
    role: str = "request_platform_control",
) -> tuple[Any, ...] | None:
    conn.execute(_ROLE_STATEMENTS[role])
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        conn.execute("RESET ROLE")
    return None if row is None else tuple(row)


def _world(
    admin_conn: PgConnection,
    *,
    requester_capabilities: tuple[str, ...] = ("platform.identity.recover",),
    approver_capabilities: tuple[str, ...] = ("platform.identity.recovery_approve",),
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    authority_id = insert_authority(admin_conn)
    identity_id = uuid4()
    credential_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"recovery-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (credential_id, identity_id, hash_password(PASSWORD)),
    )
    requester = platform_principal(admin_conn)
    for capability in requester_capabilities:
        platform_grant(admin_conn, principal_id=requester, capability=capability, delegable=False)
    approver = platform_principal(admin_conn)
    for capability in approver_capabilities:
        platform_grant(admin_conn, principal_id=approver, capability=capability, delegable=False)
    return authority_id, identity_id, credential_id, requester, approver


def _create_case(
    conn: PgConnection,
    *,
    actor: UUID,
    identity_id: UUID,
    key_digest: str | None = None,
    intent_digest: str | None = None,
) -> tuple[Any, ...]:
    _set_actor(conn, actor)
    row = _call(
        conn,
        _CREATE,
        (
            uuid4(),
            identity_id,
            "lost_credential",
            "case-ref-7f3a",
            "channel-ref-9c1b",
            key_digest or _digest(),
            intent_digest or _digest(),
        ),
    )
    assert row is not None
    return row


def _approve_case(
    conn: PgConnection, *, actor: UUID, case_id: UUID, revision: int
) -> tuple[Any, ...]:
    _set_actor(conn, actor)
    row = _call(
        conn,
        _APPROVE,
        (case_id, revision, "ownership_verified", _digest(), _digest()),
    )
    assert row is not None
    return row


def _issue_case(
    conn: PgConnection,
    *,
    actor: UUID,
    case_id: UUID,
    revision: int,
    generation: int,
    token: Any,
    key_digest: str | None = None,
    intent_digest: str | None = None,
) -> tuple[Any, ...]:
    _set_actor(conn, actor)
    row = _call(
        conn,
        _ISSUE,
        (
            case_id,
            revision,
            generation,
            token.token_id,
            token.digest,
            token.fingerprint,
            datetime.now(UTC) + timedelta(minutes=30),
            uuid4(),
            f"vault://recovery/{case_id}/{generation}",
            _digest(),
            key_digest or _digest(),
            intent_digest or _digest(),
        ),
    )
    assert row is not None
    return row


def _prepare_issue(
    conn: PgConnection,
    *,
    actor: UUID,
    case_id: UUID,
    revision: int,
    token: Any,
    key_digest: str | None = None,
    intent_digest: str | None = None,
) -> tuple[Any, ...]:
    key = key_digest or _digest()
    intent = intent_digest or _digest()
    _set_actor(conn, actor)
    prepared = _call(conn, _PREPARE, (case_id, revision, key, intent))
    assert prepared is not None
    assert prepared[0] is False
    return _issue_case(
        conn,
        actor=actor,
        case_id=case_id,
        revision=revision,
        generation=int(prepared[6]),
        token=token,
        key_digest=key,
        intent_digest=intent,
    )


def _case_status(conn: PgConnection, case_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, delivery_status, revision, recovery_intent_id, revoke_reason_code "
        "FROM request_engine.identity_recovery_cases WHERE id = %s",
        (case_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def test_governed_recovery_happy_path_links_delivery_and_consumption(
    admin_conn: PgConnection,
) -> None:
    _authority_id, identity_id, credential_id, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    assert (created[2], created[3], created[4]) == ("requested", "pending", 1)

    approved = _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)
    assert approved[2] == "approved"
    assert approved[4] == 2
    assert approved[6] is not None

    _set_actor(admin_conn, requester)
    token = issue_opaque_token()
    issue_key = _digest()
    issue_intent = _digest()
    prepared = _call(admin_conn, _PREPARE, (case_id, 2, issue_key, issue_intent))
    assert prepared is not None
    assert prepared[0] is False
    assert prepared[6] == 1

    issued = _issue_case(
        admin_conn,
        actor=requester,
        case_id=case_id,
        revision=2,
        generation=int(prepared[6]),
        token=token,
        key_digest=issue_key,
        intent_digest=issue_intent,
    )
    assert issued[2] == "issued"
    assert issued[3] == "pending"
    assert issued[4] == 3

    _set_actor(admin_conn, requester)
    replay = _call(admin_conn, _PREPARE, (case_id, 3, issue_key, issue_intent))
    assert replay is not None
    assert replay[0] is True
    reissued = _issue_case(
        admin_conn,
        actor=requester,
        case_id=case_id,
        revision=3,
        generation=int(replay[6]),
        token=issue_opaque_token(),
        key_digest=issue_key,
        intent_digest=issue_intent,
    )
    assert reissued[0] == case_id
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchone() == (1,)

    claimed = _call(admin_conn, _CLAIM, (10, 60), role="request_engine_worker")
    assert claimed is not None
    (
        ticket_id,
        claimed_case_id,
        generation,
        _reference,
        _digest_value,
        _dest,
        _expires,
        attempts,
        claim_token,
    ) = claimed
    assert UUID(str(claimed_case_id)) == case_id
    assert generation == 1
    assert attempts == 1

    delivered = _call(
        admin_conn,
        _COMPLETE,
        (ticket_id, claim_token, "delivered", None),
        role="request_engine_worker",
    )
    assert delivered == (True,)
    assert _case_status(admin_conn, case_id)[1] == "delivered"

    _set_actor(admin_conn, requester)
    consumed = _call(
        admin_conn,
        _CONSUME,
        (token.token_id, token.digest, uuid4(), hash_password(NEW_PASSWORD)),
        role="request_engine_app",
    )
    assert consumed == (identity_id,)
    status, delivery_status, revision, intent_id, _reason = _case_status(admin_conn, case_id)
    assert (status, delivery_status, revision) == ("consumed", "delivered", 6)
    assert UUID(str(intent_id)) == token.token_id

    credential_rows = admin_conn.execute(
        "SELECT id, status FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s ORDER BY id",
        (identity_id,),
    ).fetchall()
    assert (credential_id, "revoked") in credential_rows
    assert len(credential_rows) == 2

    facts = {
        str(row[0])
        for row in admin_conn.execute(
            "SELECT action FROM request_engine.platform_identity_recovery_facts WHERE case_id = %s",
            (case_id,),
        ).fetchall()
    }
    assert facts == {"request", "approve", "issue", "deliver", "consume"}

    raw_token = token.raw_token
    leaked = admin_conn.execute(
        """
        SELECT count(*) FROM (
            SELECT row_to_json(c) AS payload
              FROM request_engine.identity_recovery_cases c
            UNION ALL
            SELECT row_to_json(t)
              FROM request_engine.identity_recovery_delivery_tickets t
            UNION ALL
            SELECT row_to_json(f)
              FROM request_engine.platform_identity_recovery_facts f
            UNION ALL
            SELECT row_to_json(i)
              FROM request_engine.native_recovery_intents i
        ) AS rows
        WHERE rows.payload::text LIKE %s
        """,
        (f"%{raw_token}%",),
    ).fetchone()
    assert leaked == (0,)


def test_requester_cannot_approve_their_own_case_even_with_both_capabilities(
    admin_conn: PgConnection,
) -> None:
    _, identity_id, _, requester, _ = _world(
        admin_conn,
        requester_capabilities=("platform.identity.recover", "platform.identity.recovery_approve"),
    )
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))

    _set_actor(admin_conn, requester)
    with pytest.raises(Error) as exc:
        _call(admin_conn, _APPROVE, (case_id, 1, "ownership_verified", _digest(), _digest()))
    assert exc.value.sqlstate == "42501"
    assert _case_status(admin_conn, case_id)[0] == "requested"


def test_replay_returns_the_same_case_and_key_reuse_conflicts(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, _ = _world(admin_conn)
    key_digest = _digest()
    intent_digest = _digest()
    first = _create_case(
        admin_conn,
        actor=requester,
        identity_id=identity_id,
        key_digest=key_digest,
        intent_digest=intent_digest,
    )
    second = _create_case(
        admin_conn,
        actor=requester,
        identity_id=identity_id,
        key_digest=key_digest,
        intent_digest=intent_digest,
    )
    assert first[0] == second[0]
    assert second[2] == "requested"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_recovery_facts "
        "WHERE case_id = %s AND action = 'request'",
        (first[0],),
    ).fetchone() == (1,)

    with pytest.raises(Error) as exc:
        _create_case(
            admin_conn,
            actor=requester,
            identity_id=identity_id,
            key_digest=key_digest,
            intent_digest=_digest(),
        )
    assert exc.value.sqlstate == "23505"


def test_revoke_kills_intent_ticket_and_consumption(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)
    token = issue_opaque_token()
    _prepare_issue(admin_conn, actor=requester, case_id=case_id, revision=2, token=token)

    _set_actor(admin_conn, requester)
    revoked = _call(
        admin_conn,
        _REVOKE,
        (case_id, 3, "security_investigation", _digest(), _digest()),
    )
    assert revoked is not None
    assert revoked[2] == "revoked"
    assert revoked[4] == 4
    status, _delivery, _revision, _intent, reason = _case_status(admin_conn, case_id)
    assert (status, reason) == ("revoked", "security_investigation")
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (token.token_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchone() == ("cancelled",)

    consumed = _call(
        admin_conn,
        _CONSUME,
        (token.token_id, token.digest, uuid4(), hash_password(NEW_PASSWORD)),
        role="request_engine_app",
    )
    assert consumed == (None,)
    with pytest.raises(Error) as exc:
        _call(admin_conn, _REVOKE, (case_id, 4, "request_withdrawn", _digest(), _digest()))
    assert exc.value.sqlstate == "55000"


def test_new_issuance_supersedes_prior_live_proof(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, approver = _world(admin_conn)
    first = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    first_case = UUID(str(first[0]))
    _approve_case(admin_conn, actor=approver, case_id=first_case, revision=1)
    first_token = issue_opaque_token()
    _prepare_issue(admin_conn, actor=requester, case_id=first_case, revision=2, token=first_token)

    second = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    second_case = UUID(str(second[0]))
    _approve_case(admin_conn, actor=approver, case_id=second_case, revision=1)
    second_token = issue_opaque_token()
    _prepare_issue(admin_conn, actor=requester, case_id=second_case, revision=2, token=second_token)

    status, _delivery, revision, _intent, reason = _case_status(admin_conn, first_case)
    assert (status, reason) == ("revoked", "superseded_by_new_issuance")
    assert revision == 4
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (first_token.token_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (first_case,),
    ).fetchone() == ("cancelled",)

    first_consumed = _call(
        admin_conn,
        _CONSUME,
        (first_token.token_id, first_token.digest, uuid4(), hash_password(NEW_PASSWORD)),
        role="request_engine_app",
    )
    assert first_consumed == (None,)
    assert _call(
        admin_conn,
        _CONSUME,
        (second_token.token_id, second_token.digest, uuid4(), hash_password(NEW_PASSWORD)),
        role="request_engine_app",
    ) == (identity_id,)
    assert _case_status(admin_conn, second_case)[0] == "consumed"


def test_delivery_lease_fencing_retry_and_terminal_failure(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)
    token = issue_opaque_token()
    _prepare_issue(admin_conn, actor=requester, case_id=case_id, revision=2, token=token)

    claimed = _call(admin_conn, _CLAIM, (10, 60), role="request_engine_worker")
    assert claimed is not None
    ticket_id, _case, _generation, _ref, _digest_value, _dest, _expires, _attempts, claim_token = (
        claimed
    )

    stale = _call(
        admin_conn,
        _COMPLETE,
        (ticket_id, uuid4(), "delivered", None),
        role="request_engine_worker",
    )
    assert stale == (False,)
    assert _case_status(admin_conn, case_id)[1] == "sending"

    renewed = _call(admin_conn, _RENEW, (ticket_id, claim_token, 120), role="request_engine_worker")
    assert renewed == (True,)
    retried = _call(
        admin_conn,
        _RETRY,
        (ticket_id, claim_token, 0, "provider_timeout"),
        role="request_engine_worker",
    )
    assert retried == ("pending",)
    assert _case_status(admin_conn, case_id)[1] == "pending"

    reclaimed = _call(admin_conn, _CLAIM, (10, 60), role="request_engine_worker")
    assert reclaimed is not None
    second_token = reclaimed[8]
    assert reclaimed[7] == 2
    failed = _call(
        admin_conn,
        _COMPLETE,
        (ticket_id, second_token, "failed", "provider_rejected"),
        role="request_engine_worker",
    )
    assert failed == (True,)
    status, delivery_status, _revision, _intent, _reason = _case_status(admin_conn, case_id)
    assert (status, delivery_status) == ("issued", "failed")
    assert _call(admin_conn, _CLAIM, (10, 60), role="request_engine_worker") is None


def test_approval_expiry_and_stale_revision_are_rejected(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)

    with pytest.raises(Error) as stale:
        _issue_case(
            admin_conn,
            actor=requester,
            case_id=case_id,
            revision=1,
            generation=1,
            token=issue_opaque_token(),
        )
    assert stale.value.sqlstate == "40001"

    admin_conn.execute(
        "UPDATE request_engine.identity_recovery_cases "
        "SET approval_expires_at = clock_timestamp() - interval '1 minute' WHERE id = %s",
        (case_id,),
    )
    with pytest.raises(Error) as expired:
        _issue_case(
            admin_conn,
            actor=requester,
            case_id=case_id,
            revision=2,
            generation=1,
            token=issue_opaque_token(),
        )
    assert expired.value.sqlstate == "55000"
    assert _case_status(admin_conn, case_id)[0] == "approved"


def test_runtime_roles_cannot_invoke_recovery_commands(admin_conn: PgConnection) -> None:
    _, identity_id, _, requester, _ = _world(admin_conn)
    _set_actor(admin_conn, requester)
    with pytest.raises(Error) as exc:
        _call(
            admin_conn,
            _CREATE,
            (uuid4(), identity_id, "lost_credential", "ref", "dest", _digest(), _digest()),
            role="request_engine_app",
        )
    assert exc.value.sqlstate == "42501"
    with pytest.raises(Error) as worker_exc:
        _call(
            admin_conn,
            _CREATE,
            (uuid4(), identity_id, "lost_credential", "ref", "dest", _digest(), _digest()),
            role="request_engine_worker",
        )
    assert worker_exc.value.sqlstate == "42501"


def test_recovery_commands_acquire_the_topology_gate_first(admin_conn: PgConnection) -> None:
    functions = (
        "create_identity_recovery_case",
        "approve_identity_recovery_case",
        "prepare_identity_recovery_issue",
        "issue_identity_recovery_case",
        "revoke_identity_recovery_case",
    )
    for name in functions:
        definition = admin_conn.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'request_platform' AND p.proname = %s",
            (name,),
        ).fetchone()
        assert definition is not None
        body = str(definition[0])
        begin = body.index("BEGIN")
        first_statement = body[begin + len("BEGIN") :].lstrip()
        assert first_statement.startswith(
            "PERFORM request_engine.acquire_identity_topology_share();"
        ), f"{name} does not acquire the topology gate first"


def test_prepare_reserves_distinct_generations_and_rejects_unreserved_issue(
    admin_conn: PgConnection,
) -> None:
    _, identity_id, _, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)

    first_key = _digest()
    first_intent = _digest()
    second_key = _digest()
    second_intent = _digest()

    _set_actor(admin_conn, requester)
    first = _call(admin_conn, _PREPARE, (case_id, 2, first_key, first_intent))
    assert first is not None
    assert first[0] is False
    assert first[6] == 1

    _set_actor(admin_conn, requester)
    second = _call(admin_conn, _PREPARE, (case_id, 2, second_key, second_intent))
    assert second is not None
    assert second[0] is False
    assert second[6] == 2

    # Re-preparing the same attempt key reuses its reservation instead of
    # allocating another generation.
    _set_actor(admin_conn, requester)
    reused = _call(admin_conn, _PREPARE, (case_id, 2, first_key, first_intent))
    assert reused is not None
    assert reused[6] == 1

    # The case is approved and the revision is current, but generation 3 was
    # never reserved, so the authoritative issuance is rejected.
    with pytest.raises(Error) as unreserved:
        _issue_case(
            admin_conn,
            actor=requester,
            case_id=case_id,
            revision=2,
            generation=3,
            token=issue_opaque_token(),
            key_digest=second_key,
            intent_digest=second_intent,
        )
    assert unreserved.value.sqlstate == "40001"
    assert _case_status(admin_conn, case_id)[0] == "approved"


class _RacingRecoveryDelivery:
    """Create-if-absent staging double with a deterministic first-stager hold.

    The real command path and real PostgreSQL transactions are exercised by the
    race proof; only the external secret store is doubled. The first issuance to
    reach ``stage`` (the one that started first and therefore reserved the lower
    generation) creates its key and is parked until the second issuance has
    staged and committed its authoritative transaction. Under the reservation
    contract the two issuances reserve distinct generations, so each creates its
    own key and the losing first issuance discards only its own generation.
    Without the reservation both compute the same generation: the first creates
    the key, the second observes it retained (``created=False``), and the first
    then discards the retained key the winner's ticket references.
    ``discard`` also removes the retained secret, mirroring the real delete, so a
    stray discard is observable as a missing retained secret.
    """

    def __init__(self) -> None:
        self._staged: dict[tuple[UUID, int], tuple[str, str, datetime]] = {}
        self.discarded: list[tuple[UUID, int]] = []
        self._stage_calls = 0
        self.first_staged = asyncio.Event()
        self.second_staged = asyncio.Event()
        self.release_first = asyncio.Event()

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        key = (case_id, generation)
        reference = f"vault://recovery/{case_id}/{generation}"
        retained = self._staged.get(key)
        if retained is None:
            self._staged[key] = (secret, reference, expires_at)
            created = True
        else:
            secret, reference, expires_at = retained
            created = False
        self._stage_calls += 1
        if self._stage_calls == 1:
            self.first_staged.set()
            await self.release_first.wait()
        else:
            self.second_staged.set()
        return StagedRecoverySecret(
            reference=reference,
            digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
            created=created,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.discarded.append((case_id, generation))
        self._staged.pop((case_id, generation), None)

    async def publish(
        self, *, reference: str, destination_reference: str, idempotency_key: str
    ) -> DeliveryOutcome:
        return DeliveryOutcome.DELIVERED

    async def reconcile(self, *, reference: str, idempotency_key: str) -> DeliveryOutcome | None:
        return None

    def retained(self, case_id: UUID, generation: int) -> str | None:
        entry = self._staged.get((case_id, generation))
        return None if entry is None else entry[0]


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_issuance_keeps_the_retained_secret(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
) -> None:
    """Two concurrent issuances reserve distinct generations and stage distinct keys.

    The first issuance reserves generation 1 and stages its own key, then parks
    inside staging. The second reserves generation 2, stages its own key and
    commits the authoritative issuance. The first then loses the revision race
    and discards only its own generation, so the winner's retained secret
    survives and matches the delivery ticket. Without the reservation both
    issuances would compute generation 1 and the losing first issuance would
    delete the retained key the winner's ticket references.
    """

    _, identity_id, _, requester, approver = _world(admin_conn)
    created = _create_case(admin_conn, actor=requester, identity_id=identity_id)
    case_id = UUID(str(created[0]))
    _approve_case(admin_conn, actor=approver, case_id=case_id, revision=1)
    expected_revision = int(_case_status(admin_conn, case_id)[2])
    assert expected_revision == 2

    delivery = _RacingRecoveryDelivery()
    commands = PostgresIdentityRecoveryCommands(platform_control_session_factory, delivery)
    actor = PlatformActorContext(
        principal_id=requester,
        capabilities=frozenset({"platform.identity.recover"}),
        authority_revision=principal_revision(admin_conn, requester),
    )
    first_command = IssueIdentityRecoveryCaseCommand(
        case_id=case_id,
        expected_revision=expected_revision,
        idempotency_key=f"race-issue-{uuid4().hex}",
    )
    second_command = IssueIdentityRecoveryCaseCommand(
        case_id=case_id,
        expected_revision=expected_revision,
        idempotency_key=f"race-issue-{uuid4().hex}",
    )

    # The first issuance reserves the lower generation and is parked inside
    # ``stage`` before the second starts, so both reserve before either issues.
    first = asyncio.create_task(commands.issue_case(actor, first_command))
    await asyncio.wait_for(delivery.first_staged.wait(), timeout=30)
    second = asyncio.create_task(commands.issue_case(actor, second_command))
    await asyncio.wait_for(delivery.second_staged.wait(), timeout=30)

    winner = await asyncio.wait_for(second, timeout=60)
    delivery.release_first.set()
    with pytest.raises((IdentityRecoveryConflict, IdentityRecoveryRevisionConflict)):
        await asyncio.wait_for(first, timeout=60)

    assert isinstance(winner, IdentityRecoveryCaseView)
    generation = winner.issuance_generation
    retained = delivery.retained(case_id, generation)
    assert retained is not None, "the winning staged secret was deleted by the losing issuance"
    assert generation == 2, f"expected generation 2 from the second issuance, got {generation}"
    assert set(delivery.discarded) == {(case_id, 1)}, (
        f"the losing issuance must discard only its own generation, got {delivery.discarded!r}"
    )
    retained_digest = hashlib.sha256(retained.encode("utf-8")).hexdigest()

    tickets = admin_conn.execute(
        "SELECT generation, status, secret_reference, secret_digest "
        "FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchall()
    assert len(tickets) == 1, f"expected exactly one delivery ticket, got {tickets!r}"
    ticket_generation, ticket_status, ticket_reference, ticket_digest = tickets[0]
    assert (ticket_generation, ticket_status) == (generation, "pending")
    assert ticket_reference == f"vault://recovery/{case_id}/{generation}"
    assert ticket_digest == retained_digest, (
        "PostgreSQL retained a different secret than the staged winner"
    )

    status, delivery_status, revision, _intent_id, revoke_reason = _case_status(admin_conn, case_id)
    assert (status, delivery_status, revision, revoke_reason) == ("issued", "pending", 3, None)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_recovery_intents "
        "WHERE native_identity_id = %s AND status = 'pending'",
        (identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_recovery_facts "
        "WHERE case_id = %s AND action = 'issue'",
        (case_id,),
    ).fetchone() == (1,)
