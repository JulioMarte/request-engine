"""PostgreSQL proofs for verified Native HUMAN recovery addresses."""

from uuid import UUID, uuid4

import psycopg
import pytest

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.native_recovery_address_store import (
    PostgresNativeRecoveryAddressStore,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import DeliveryOutcome
from request_engine.platform.security.native_recovery_addresses import (
    NativeRecoveryAddressInvalid,
    NativeRecoveryAddressService,
)

from .conftest import PgConnection

pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


class RecordingMessenger:
    def __init__(self) -> None:
        self.verifications: list[tuple[str, str]] = []
        self.recoveries: list[tuple[str, str]] = []

    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        del idempotency_key
        self.verifications.append((secret, destination_reference))
        return DeliveryOutcome.DELIVERED

    async def send_recovery(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        del idempotency_key
        self.recoveries.append((secret, destination_reference))
        return DeliveryOutcome.DELIVERED


async def _identity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> tuple[UUID, UUID, str]:
    authority_id = uuid4()
    handle = f"recovery-address-{uuid4().hex}@example.test"
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"recovery-address-{uuid4().hex}"),
    )
    enrolled = await build_native_auth_runtime(session_factory).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=handle,
        password="verified recovery address password",
    )
    return authority_id, enrolled.native_identity_id, handle


@pytest.mark.asyncio
async def test_verified_address_proofs_are_digest_only_one_time_and_throttled(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id, identity_id, handle = await _identity(
        admin_conn,
        command_session_factory,
    )
    messenger = RecordingMessenger()
    service = NativeRecoveryAddressService(
        store=PostgresNativeRecoveryAddressStore(command_session_factory),
        messenger=messenger,
    )
    destination = f"Backup-{uuid4().hex}@Example.Test"

    prepared = await service.prepare_email(
        native_identity_id=identity_id,
        address=destination,
    )
    assert prepared.status == "pending"
    assert prepared.verification_created is True
    assert len(messenger.verifications) == 1
    verification_secret, normalized_destination = messenger.verifications[0]
    assert normalized_destination == destination.casefold()

    verification = admin_conn.execute(
        """
        SELECT token_digest, token_fingerprint, status
          FROM request_engine.native_recovery_address_verifications
         WHERE recovery_address_id = %s
        """,
        (prepared.address_id,),
    ).fetchone()
    assert verification is not None
    assert len(bytes(verification[0])) == 32
    assert verification_secret.encode("utf-8") != bytes(verification[0])
    assert len(str(verification[1])) == 16
    assert verification[2] == "pending"

    verified_identity = await service.verify(raw_token=verification_secret)
    assert verified_identity == identity_id
    with pytest.raises(NativeRecoveryAddressInvalid):
        await service.verify(raw_token=verification_secret)

    addresses = await service.list_for_identity(native_identity_id=identity_id)
    assert len(addresses) == 1
    assert addresses[0].status == "verified"
    assert addresses[0].normalized_address == destination.casefold()

    await service.request_recovery(
        identity_authority_id=authority_id,
        login_handle=handle,
    )
    await service.request_recovery(
        identity_authority_id=authority_id,
        login_handle=handle,
    )
    assert len(messenger.recoveries) == 1

    recovery_secret, recovery_destination = messenger.recoveries[0]
    assert recovery_destination == destination.casefold()
    intent = admin_conn.execute(
        """
        SELECT token_digest, token_fingerprint, status
          FROM request_engine.native_recovery_intents
         WHERE native_identity_id = %s
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (identity_id,),
    ).fetchone()
    assert intent is not None
    assert len(bytes(intent[0])) == 32
    assert recovery_secret.encode("utf-8") != bytes(intent[0])
    assert len(str(intent[1])) == 16
    assert intent[2] == "pending"
    assert admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.native_recovery_address_facts
         WHERE native_identity_id = %s
           AND event_kind = 'recovery_requested'
        """,
        (identity_id,),
    ).fetchone() == (1,)


def test_recovery_address_tables_are_private_and_facts_append_only(
    admin_conn: PgConnection,
) -> None:
    for table in (
        "request_engine.native_recovery_addresses",
        "request_engine.native_recovery_address_verifications",
        "request_engine.native_recovery_address_facts",
    ):
        assert admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'SELECT')",
            (table,),
        ).fetchone() == (False,)

    authority_id = uuid4()
    identity_id = uuid4()
    address_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"append-only-recovery-address-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
        "VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"append-only-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.native_recovery_addresses(
            id, native_identity_id, kind, normalized_address
        ) VALUES (%s, %s, 'email', %s)
        """,
        (address_id, identity_id, f"append-only-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.native_recovery_address_facts(
            native_identity_id, recovery_address_id, event_kind
        ) VALUES (%s, %s, 'verification_requested')
        """,
        (identity_id, address_id),
    )
    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            "UPDATE request_engine.native_recovery_address_facts "
            "SET event_kind = event_kind WHERE recovery_address_id = %s",
            (address_id,),
        )


_RECOVERY_ADDRESS_FUNCTIONS = (
    "prepare_native_recovery_address(uuid,uuid,text,text,uuid,bytea,text,timestamptz)",
    "verify_native_recovery_address(uuid,bytea)",
    "read_native_recovery_addresses(uuid)",
    "revoke_native_recovery_address(uuid,uuid)",
    "create_native_recovery_intent_for_verified_address(uuid,text,uuid,bytea,text,timestamptz)",
)


def test_recovery_address_functions_are_least_privilege(
    admin_conn: PgConnection,
) -> None:
    for signature in _RECOVERY_ADDRESS_FUNCTIONS:
        row = admin_conn.execute(
            """
            SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig,
                   has_function_privilege('request_engine_app', p.oid, 'EXECUTE'),
                   EXISTS (
                       SELECT 1
                         FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))
                        WHERE grantee = 0
                          AND privilege_type = 'EXECUTE'
                   )
              FROM pg_proc AS p
             WHERE p.oid = to_regprocedure(%s)
            """,
            (f"request_auth.{signature}",),
        ).fetchone()
        assert row is not None, signature
        assert row[0:2] == ("request_engine_schema_owner", True), signature
        assert row[2] == ["search_path=pg_catalog, request_engine"], signature
        assert row[3] is True, signature
        assert row[4] is False, signature
