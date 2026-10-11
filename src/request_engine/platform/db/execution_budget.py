"""Connection-scoped containment for HTTP SQL, separate from worker/migration policy."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PostgresPoolBudget:
    """Per-engine connection ceiling; deployment totals include every process."""

    size: int = 5
    max_overflow: int = 10

    def __post_init__(self) -> None:
        if (
            type(self.size) is not int
            or type(self.max_overflow) is not int
            or not 1 <= self.size <= 64
            or not 0 <= self.max_overflow <= 64
        ):
            raise ValueError("Invalid PostgreSQL pool budget")

    @classmethod
    def from_environment(cls) -> "PostgresPoolBudget":
        return cls(
            size=int(os.environ.get("REQUEST_ENGINE_DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("REQUEST_ENGINE_DB_POOL_MAX_OVERFLOW", "10")),
        )


@dataclass(frozen=True, slots=True)
class PostgresExecutionBudget:
    statement_ms: int = 30_000
    lock_ms: int = 5_000
    transaction_ms: int = 60_000
    idle_transaction_ms: int = 60_000
    pool_seconds: float = 5

    def __post_init__(self) -> None:
        if not (
            0 < self.lock_ms < self.statement_ms <= 120_000
            and self.statement_ms < self.transaction_ms <= 300_000
            and 0 < self.idle_transaction_ms <= 300_000
            and 0 < self.pool_seconds <= 30
        ):
            raise ValueError("Invalid PostgreSQL execution budget")

    @classmethod
    def http_from_environment(cls) -> "PostgresExecutionBudget":
        return cls(
            statement_ms=int(os.environ.get("REQUEST_ENGINE_HTTP_SQL_STATEMENT_MS", "30000")),
            lock_ms=int(os.environ.get("REQUEST_ENGINE_HTTP_SQL_LOCK_MS", "5000")),
            transaction_ms=int(os.environ.get("REQUEST_ENGINE_HTTP_SQL_TRANSACTION_MS", "60000")),
            idle_transaction_ms=int(
                os.environ.get("REQUEST_ENGINE_HTTP_SQL_IDLE_TRANSACTION_MS", "60000")
            ),
            pool_seconds=float(os.environ.get("REQUEST_ENGINE_HTTP_SQL_POOL_SECONDS", "5")),
        )

    def server_settings(self) -> dict[str, str]:
        return {
            "statement_timeout": str(self.statement_ms),
            "lock_timeout": str(self.lock_ms),
            "transaction_timeout": str(self.transaction_ms),
            "idle_in_transaction_session_timeout": str(self.idle_transaction_ms),
        }
