import pytest

from request_engine.platform.db.execution_budget import PostgresExecutionBudget


@pytest.mark.parametrize("lock", [0, -1, 30000, 40000])
def test_lock_budget_cannot_be_disabled_or_hidden_by_statement_timeout(lock: int) -> None:
    with pytest.raises(ValueError):
        PostgresExecutionBudget(lock_ms=lock)


def test_http_budget_environment_is_closed_and_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_HTTP_SQL_POOL_SECONDS", "nan")
    with pytest.raises(ValueError):
        PostgresExecutionBudget.http_from_environment()
