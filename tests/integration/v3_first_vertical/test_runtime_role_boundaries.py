import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import SessionFactory


async def _identity(factory: SessionFactory) -> tuple[str, str, bool, bool, bool, bool]:
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT current_user,
                           session_user,
                           pg_has_role(current_user, 'request_engine_app', 'member'),
                           pg_has_role(current_user, 'request_engine_worker', 'member'),
                           pg_has_role(current_user, 'request_engine_admin', 'member'),
                           rolsuper
                    FROM pg_roles
                    WHERE rolname = current_user
                    """
                )
            )
        ).one()
        return (
            str(row[0]),
            str(row[1]),
            bool(row[2]),
            bool(row[3]),
            bool(row[4]),
            bool(row[5]),
        )


async def _assert_set_role_forbidden(factory: SessionFactory, target_role: str) -> None:
    async with factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text(f"SET ROLE {target_role}"))
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_application_login_has_only_application_runtime_membership(
    app_session_factory: SessionFactory,
) -> None:
    current_user, session_user, app, worker, admin, superuser = await _identity(
        app_session_factory
    )
    assert current_user == session_user
    assert current_user.startswith("request_engine_app_test_")
    assert (app, worker, admin, superuser) == (True, False, False, False)

    await _assert_set_role_forbidden(app_session_factory, "request_engine_worker")
    await _assert_set_role_forbidden(app_session_factory, "request_engine_admin")
    await _assert_set_role_forbidden(app_session_factory, "request_engine_schema_owner")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_worker_login_has_only_worker_runtime_membership(
    worker_session_factory: SessionFactory,
) -> None:
    current_user, session_user, app, worker, admin, superuser = await _identity(
        worker_session_factory
    )
    assert current_user == session_user
    assert current_user.startswith("request_engine_worker_test_")
    assert (app, worker, admin, superuser) == (False, True, False, False)

    await _assert_set_role_forbidden(worker_session_factory, "request_engine_app")
    await _assert_set_role_forbidden(worker_session_factory, "request_engine_admin")
    await _assert_set_role_forbidden(worker_session_factory, "request_engine_schema_owner")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_admin_login_does_not_inherit_schema_ownership_or_runtime_roles(
    runtime_admin_session_factory: SessionFactory,
) -> None:
    current_user, session_user, app, worker, admin, superuser = await _identity(
        runtime_admin_session_factory
    )
    assert current_user == session_user
    assert current_user.startswith("request_engine_admin_test_")
    assert (app, worker, admin, superuser) == (False, False, True, False)

    await _assert_set_role_forbidden(runtime_admin_session_factory, "request_engine_app")
    await _assert_set_role_forbidden(runtime_admin_session_factory, "request_engine_worker")
    await _assert_set_role_forbidden(
        runtime_admin_session_factory, "request_engine_schema_owner"
    )
