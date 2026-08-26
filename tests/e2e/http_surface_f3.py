from .http_surface import PublicHttpOperation
from .http_surface_f3_resource import F3_RESOURCE_OPERATIONS
from .http_surface_f3_service import F3_SERVICE_OPERATIONS

F3_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = F3_SERVICE_OPERATIONS + F3_RESOURCE_OPERATIONS
