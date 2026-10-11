import pytest

from request_engine.platform.db.execution_budget import PostgresExecutionBudget, PostgresPoolBudget


@pytest.mark.parametrize("lock", [0, -1, 30000, 40000])
def test_lock_budget_cannot_be_disabled_or_hidden_by_statement_timeout(lock: int) -> None:
    with pytest.raises(ValueError):
        PostgresExecutionBudget(lock_ms=lock)


def test_http_budget_environment_is_closed_and_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_HTTP_SQL_POOL_SECONDS", "nan")
    with pytest.raises(ValueError):
        PostgresExecutionBudget.http_from_environment()


@pytest.mark.parametrize(
    ("size", "overflow"),
    [(0, 0), (-1, 0), (65, 0), (1, -1), (1, 65), (True, 0), (1, True)],
)
def test_connection_pool_cannot_be_unbounded(size: int, overflow: int) -> None:
    with pytest.raises(ValueError, match="pool budget"):
        PostgresPoolBudget(size=size, max_overflow=overflow)


@pytest.mark.parametrize(
    "setting", ["REQUEST_ENGINE_DB_POOL_SIZE", "REQUEST_ENGINE_DB_POOL_MAX_OVERFLOW"]
)
@pytest.mark.parametrize("value", ["nan", "inf", "1.5", "-1"])
def test_pool_environment_fails_closed(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: str
) -> None:
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        PostgresPoolBudget.from_environment()


def test_pool_environment_accepts_fixed_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_DB_POOL_SIZE", "2")
    monkeypatch.setenv("REQUEST_ENGINE_DB_POOL_MAX_OVERFLOW", "0")
    budget = PostgresPoolBudget.from_environment()
    assert budget.size == 2
    assert budget.max_overflow == 0
