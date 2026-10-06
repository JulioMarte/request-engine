"""Bound costly password work, including work whose HTTP caller disconnects."""

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import BoundedSemaphore


class PasswordWorkCapacityExceeded(RuntimeError):
    """No password work was admitted; the caller may retry with bounded backoff."""


class PasswordWorkExecutor:
    def __init__(self, *, capacity: int = 4) -> None:
        if not 1 <= capacity <= 32:
            raise ValueError("password work capacity must be between 1 and 32")
        self._slots = BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="re-password")

    async def run[T, **P](self, operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        if not self._slots.acquire(blocking=False):
            raise PasswordWorkCapacityExceeded("Password work capacity is temporarily exhausted")
        try:
            future = self._executor.submit(partial(operation, *args, **kwargs))
        except BaseException:
            self._slots.release()
            raise
        # Release on actual thread completion, not HTTP/task cancellation. Even
        # cancellation before execution releases once through this callback.
        future.add_done_callback(lambda _: self._slots.release())
        return await asyncio.wrap_future(future)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


_PASSWORD_WORK = PasswordWorkExecutor(
    capacity=int(os.environ.get("REQUEST_ENGINE_PASSWORD_WORK_CAPACITY", "4"))
)


async def run_password_work[T, **P](
    operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    return await _PASSWORD_WORK.run(operation, *args, **kwargs)
