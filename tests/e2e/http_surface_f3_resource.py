from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

P1 = "00000000-0000-4000-8000-000000000001"

F3_RESOURCE_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "resource_activity.read",
        "GET",
        "/v1/resource-activities",
        "resource_activity.read",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/resource-activities", (("resource_id", P1),)),
    ),
    PublicHttpOperation(
        "resource_activity.start",
        "POST",
        "/v1/resource-activities",
        "resource_activity.start",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/resource-activities",
            body={"resource_id": P1, "kind": "break"},
        ),
    ),
    PublicHttpOperation(
        "resource_activity.end",
        "POST",
        "/v1/resource-activities/{resource_activity_id}/end",
        "resource_activity.end",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/resource-activities/{P1}/end", body={"expected_revision": 1}),
    ),
    PublicHttpOperation(
        "workload.list",
        "GET",
        "/v1/live-workloads",
        "workload.list",
        False,
        False,
        TenantIsolationMode.FILTERED,
        HttpProbe("/v1/live-workloads"),
    ),
)
