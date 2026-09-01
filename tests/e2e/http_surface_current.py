from .http_surface import PUBLIC_HTTP_OPERATIONS as V3_HTTP_OPERATIONS
from .http_surface import PublicHttpOperation
from .http_surface_f3 import F3_HTTP_OPERATIONS
from .http_surface_f4 import F4_HTTP_OPERATIONS
from .http_surface_f5 import F5_HTTP_OPERATIONS
from .http_surface_f5_workflow import F5_WORKFLOW_HTTP_OPERATIONS
from .http_surface_f6 import F6_HTTP_OPERATIONS
from .http_surface_f6_tools import F6_TOOL_HTTP_OPERATIONS
from .http_surface_f7 import F7_HTTP_OPERATIONS
from .http_surface_s0b import S0B_HTTP_OPERATIONS

PUBLIC_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    V3_HTTP_OPERATIONS
    + F3_HTTP_OPERATIONS
    + F4_HTTP_OPERATIONS
    + F5_HTTP_OPERATIONS
    + F5_WORKFLOW_HTTP_OPERATIONS
    + F6_HTTP_OPERATIONS
    + F6_TOOL_HTTP_OPERATIONS
    + F7_HTTP_OPERATIONS
    + S0B_HTTP_OPERATIONS
)

MATRIX_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    V3_HTTP_OPERATIONS + F7_HTTP_OPERATIONS + S0B_HTTP_OPERATIONS
)


def operation_keys() -> frozenset[tuple[str, str]]:
    return frozenset(operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS)
