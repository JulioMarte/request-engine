from .http_surface import HttpProbe, PublicHttpOperation, TenantIsolationMode

P1 = "00000000-0000-4000-8000-000000000001"
P2 = "00000000-0000-4000-8000-000000000002"
P3 = "00000000-0000-4000-8000-000000000003"

F4_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "live_capacity.scope.create",
        "POST",
        "/v1/live-capacity/projection-policies",
        "live_capacity.configure_scope",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/live-capacity/projection-policies",
            body={"service_queue_id": P1, "resource_id": P2, "location_id": P3},
        ),
    ),
    PublicHttpOperation(
        "live_capacity.scope.update",
        "POST",
        "/v1/live-capacity/projection-policies/{policy_id}",
        "live_capacity.configure_scope",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/live-capacity/projection-policies/{P1}",
            body={
                "resource_id": P2,
                "location_id": P3,
                "active": True,
                "expected_revision": 1,
            },
        ),
    ),
    PublicHttpOperation(
        "live_capacity.estimate.create",
        "POST",
        "/v1/live-capacity/workload-estimate-policies",
        "live_capacity.configure_estimate",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            "/v1/live-capacity/workload-estimate-policies",
            body={"workload_classification_id": P1, "duration_seconds": 1200},
        ),
    ),
    PublicHttpOperation(
        "live_capacity.estimate.update",
        "POST",
        "/v1/live-capacity/workload-estimate-policies/{policy_id}",
        "live_capacity.configure_estimate",
        True,
        True,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/live-capacity/workload-estimate-policies/{P1}",
            body={"duration_seconds": 1200, "active": True, "expected_revision": 1},
        ),
    ),
    PublicHttpOperation(
        "live_capacity.staff.read",
        "GET",
        "/v1/live-capacity/queues/{service_queue_id}",
        "live_capacity.read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(f"/v1/live-capacity/queues/{P1}"),
    ),
    PublicHttpOperation(
        "live_capacity.customer.read",
        "GET",
        "/v1/live-capacity/queues/{service_queue_id}/customer",
        "live_capacity.customer_read",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/live-capacity/queues/{P1}/customer",
            (("subject_party_id", P2),),
        ),
    ),
    PublicHttpOperation(
        "live_capacity.intake.evaluate",
        "GET",
        "/v1/live-capacity/queues/{service_queue_id}/evaluate-intake",
        "live_capacity.evaluate_intake",
        False,
        False,
        TenantIsolationMode.NOT_FOUND,
        HttpProbe(
            f"/v1/live-capacity/queues/{P1}/evaluate-intake",
            (("workload_classification_id", P2),),
        ),
    ),
)
