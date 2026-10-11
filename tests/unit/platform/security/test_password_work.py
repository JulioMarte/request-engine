"""Cancellation must not turn bounded password work into unbounded threads."""

import asyncio
from threading import Event

import pytest

from request_engine.platform.security.password_work import (
    PasswordWorkCapacityExceeded,
    PasswordWorkExecutor,
)


@pytest.mark.asyncio
async def test_running_work_keeps_capacity_after_caller_cancellation() -> None:
    executor = PasswordWorkExecutor(capacity=1)
    entered, release = Event(), Event()
    calls: list[str] = []

    def costly() -> str:
        calls.append("started")
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test synchronization failed")
        return "done"

    task = asyncio.create_task(executor.run(costly))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(PasswordWorkCapacityExceeded):
            await executor.run(costly)
        assert calls == ["started"]
    finally:
        release.set()
        await asyncio.to_thread(executor.close)


@pytest.mark.asyncio
async def test_success_and_failure_release_capacity() -> None:
    executor = PasswordWorkExecutor(capacity=1)

    def failure() -> None:
        raise ValueError("operation failed")

    try:
        assert await executor.run(lambda: 7) == 7
        with pytest.raises(ValueError, match="operation failed"):
            await executor.run(failure)
        assert await executor.run(lambda: 9) == 9
    finally:
        executor.close()


@pytest.mark.parametrize("capacity", [0, -1, 33])
def test_invalid_capacity_cannot_disable_guard(capacity: int) -> None:
    with pytest.raises(ValueError):
        PasswordWorkExecutor(capacity=capacity)
