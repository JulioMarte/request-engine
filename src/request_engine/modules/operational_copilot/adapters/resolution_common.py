from typing import TypeVar

from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    CopilotResolutionFailed,
)

T = TypeVar("T")


def require_one(values: tuple[T, ...], label: str) -> T:
    if not values:
        raise CopilotResolutionFailed(f"no tenant-scoped {label} matched")
    if len(values) != 1:
        raise AmbiguousCopilotIntent(f"multiple tenant-scoped {label} values matched")
    return values[0]
