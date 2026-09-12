from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import SessionTokenInvalid
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import (
    NativeIdentityAuthorityDisabled,
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.security]
PASSWORD = "correct horse battery staple"


@pytest.mark.asyncio
async def test_native_human_login_and_revocation_use_least_privilege_runtime_boundary(
    admin_conn: object,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    login_handle = f"native-{uuid4().hex}@example.test"
    admin = admin_conn
    assert hasattr(admin, "execute")
    admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.identity_authorities (
            id, kind, issuer_or_environment
        ) VALUES (%s, 'native', %s)
        """,
        (authority_id, f"test:{authority_id}"),
    )

    store = PostgresNativeHumanAuthStore(command_session_factory)
    service = NativeHumanAuthService(
        store=store,
        clock=lambda: datetime.now(UTC),
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(command_session_factory)
    )
    enrollment = None
    try:
        async with command_session_factory() as session, session.begin():
            can_read_credentials = (
                await session.execute(
                    text(
                        "SELECT has_table_privilege(current_user, "
                        "'request_engine.native_credentials', 'SELECT')"
                    )
                )
            ).scalar_one()
        assert can_read_credentials is False

        enrollment = await service.enroll_password_identity(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password=PASSWORD,
        )
        issued = await service.authenticate_password(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password=PASSWORD,
        )
        subject = await authenticator.authenticate(NativeSessionEvidence(issued.raw_token))
        assert subject.subject_id == str(enrollment.native_identity_id)
        assert "capabilities" not in subject.metadata

        await service.revoke_all_sessions(native_identity_id=enrollment.native_identity_id)
        with pytest.raises(SessionTokenInvalid):
            await authenticator.authenticate(NativeSessionEvidence(issued.raw_token))
    finally:
        if enrollment is not None:
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_recovery_intents WHERE native_identity_id = %s",
                (enrollment.native_identity_id,),
            )
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_sessions WHERE native_identity_id = %s",
                (enrollment.native_identity_id,),
            )
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_credentials WHERE native_identity_id = %s",
                (enrollment.native_identity_id,),
            )
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_identities WHERE id = %s",
                (enrollment.native_identity_id,),
            )
        admin.execute(  # type: ignore[attr-defined]
            "DELETE FROM request_engine.identity_authorities WHERE id = %s", (authority_id,)
        )


@pytest.mark.asyncio
async def test_disabling_native_identity_authority_invalidates_existing_session(
    admin_conn: object,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    login_handle = f"native-{uuid4().hex}@example.test"
    admin = admin_conn
    assert hasattr(admin, "execute")
    admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.identity_authorities (
            id, kind, issuer_or_environment
        ) VALUES (%s, 'native', %s)
        """,
        (authority_id, f"test:{authority_id}"),
    )
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(command_session_factory)
    )
    enrollment = None
    try:
        enrollment = await service.enroll_password_identity(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password=PASSWORD,
        )
        issued = await service.authenticate_password(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password=PASSWORD,
        )
        admin.execute(  # type: ignore[attr-defined]
            "UPDATE request_engine.identity_authorities SET status = 'disabled' WHERE id = %s",
            (authority_id,),
        )

        with pytest.raises(NativeIdentityAuthorityDisabled):
            await authenticator.authenticate(NativeSessionEvidence(issued.raw_token))
    finally:
        if enrollment is not None:
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_sessions WHERE native_identity_id = %s",
                (enrollment.native_identity_id,),
            )
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_credentials WHERE native_identity_id = %s",
                (enrollment.native_identity_id,),
            )
            admin.execute(  # type: ignore[attr-defined]
                "DELETE FROM request_engine.native_identities WHERE id = %s",
                (enrollment.native_identity_id,),
            )
        admin.execute(  # type: ignore[attr-defined]
            "DELETE FROM request_engine.identity_authorities WHERE id = %s", (authority_id,)
        )
