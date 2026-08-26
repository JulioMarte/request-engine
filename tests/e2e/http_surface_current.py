from .http_surface import PUBLIC_HTTP_OPERATIONS as V3_HTTP_OPERATIONS
from .http_surface import PublicHttpOperation
from .http_surface_f3 import F3_HTTP_OPERATIONS
from .http_surface_f4 import F4_HTTP_OPERATIONS

PUBLIC_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    V3_HTTP_OPERATIONS + F3_HTTP_OPERATIONS + F4_HTTP_OPERATIONS
)


def operation_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS)
