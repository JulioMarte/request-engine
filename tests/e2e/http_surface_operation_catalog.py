from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

OPERATION_CATALOG_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "operation_catalog.list_authorized",
        "GET",
        "/v1/operation-catalog",
        None,
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/operation-catalog"),
    ),
)
