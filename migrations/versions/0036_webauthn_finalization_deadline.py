"""Keep challenge expiry binding through every atomic WebAuthn effect."""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "0036_webauthn_deadline"
down_revision: str | None = "0035_adoption_recovery"
branch_labels: str | None = None
depends_on: str | None = None


def _enforce_deadline(signature: str, first_write: str, expiry: str, result: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    consume = "UPDATE request_engine.webauthn_challenges"
    success = "RETURN QUERY SELECT v_identity;" if result == "RETURN;" else "RETURN true;"
    for anchor in (first_write, consume, success):
        if definition.count(anchor) != 1:
            raise RuntimeError(f"Migration anchor missing or ambiguous in {signature}: {anchor}")

    # Existing lock acquisition and validation are unchanged. The first check
    # prevents a ceremony admitted before a lock wait from writing after expiry.
    # The second check handles structural UNIQUE/FK/trigger waits during writes.
    # Its private exception rolls back only the effect block; the already-held
    # challenge/authority/identity/credential/session locks remain in the parent.
    definition = definition.replace(
        first_write,
        f"IF {expiry} THEN {result} END IF;\n\n            BEGIN\n            " + first_write,
        1,
    )
    definition = definition.replace(
        consume,
        f"IF {expiry} THEN\n"
        "                    RAISE EXCEPTION 'WebAuthn finalization deadline elapsed'\n"
        "                        USING ERRCODE='PWE01';\n"
        "                END IF;\n\n            " + consume,
        1,
    )
    definition = definition.replace(
        success,
        success + "\n            EXCEPTION WHEN SQLSTATE 'PWE01' THEN\n"
        f"                {result}\n            END;",
        1,
    )
    # CREATE OR REPLACE retains the function OID, owner and current ACLs; only
    # the bodies change. psycopg interprets literal %ROWTYPE as pyformat syntax.
    op.get_bind().exec_driver_sql(definition.replace("%", "%%"))


def upgrade() -> None:
    _enforce_deadline(
        "request_auth.finalize_webauthn_registration("
        "bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean)",
        "INSERT INTO request_engine.webauthn_credentials",
        "v_challenge.expires_at <= clock_timestamp()",
        "RETURN false;",
    )
    _enforce_deadline(
        "request_auth.finalize_setup_webauthn_registration("
        "bytea,uuid,bytea,bytea,bigint,text,boolean,boolean,boolean,uuid)",
        "INSERT INTO request_engine.setup_pending_webauthn_credential",
        "v_challenge.expires_at <= clock_timestamp() OR v_expires_at <= clock_timestamp()",
        "RETURN false;",
    )
    _enforce_deadline(
        "request_auth.finalize_webauthn_authentication("
        "bytea,uuid,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz)",
        "UPDATE request_engine.webauthn_credentials",
        "v_challenge.expires_at <= clock_timestamp() OR p_expires_at <= clock_timestamp()",
        "RETURN false;",
    )
    _enforce_deadline(
        "request_auth.finalize_webauthn_step_up(bytea,uuid,uuid,uuid,bigint,boolean,boolean)",
        "UPDATE request_engine.webauthn_credentials",
        "v_challenge.expires_at <= clock_timestamp() OR v_session.expires_at <= clock_timestamp()",
        "RETURN false;",
    )
    _enforce_deadline(
        "request_auth.finalize_discoverable_webauthn_authentication("
        "bytea,uuid,bigint,boolean,boolean,boolean,uuid,bytea,text,timestamptz,uuid,bytea)",
        "UPDATE request_engine.webauthn_credentials",
        "v_challenge.expires_at <= clock_timestamp() OR p_expires_at <= clock_timestamp()",
        "RETURN;",
    )


def downgrade() -> None:
    raise RuntimeError("WebAuthn finalization deadlines are roll-forward only")
