# Delivery module

> **V3 status: narrowly reactivated/incubating for `ReservationAccess`.**
> Advanced execution/fulfillment concepts remain deferred and are not baseline dependencies.

Delivery owns the post-commit access artifacts required to execute a confirmed Reservation without
making Booking provider-aware. The currently admitted capability is deliberately small:

```text
Booking Reservation commit
        |
        | reservation.* outbox fact
        v
Reservation lifecycle worker
        |
        | Delivery contract
        v
ReservationAccess
        |
        | provider port (optional)
        v
Meet / Zoom / Teams / LiveKit / phone bridge / other access provider
```

## Ownership boundary

Delivery currently owns:

- `OfferingVersion.delivery_policy` interpretation for access artifacts;
- `ReservationAccess` materialization/revocation;
- provider-neutral access kinds (`video_link`, `phone`, `physical_location`, `instructions`,
  `external_session`);
- semantic provider materialization identity and reconciliation.

Delivery still does **not** activate the former V2 `ServiceSession`, `Fulfillment`, `OutcomeScope`,
correction, admission, queue, or payment models. Queue ownership remains in `queue`. Booking remains
the sole owner of Reservation/capacity truth.

Baseline modules must not import Delivery. Composition happens in
`entrypoints/worker/reservation_lifecycle.py`, which depends on the public contracts of both sides.

## Delivery policy contract

`OfferingVersion.delivery_policy` is immutable operational configuration. Invalid configuration
must not be treated as ordinary poison work after a Reservation has already been committed.

The canonical shape is:

```json
{
  "access": [
    {
      "key": "video",
      "kind": "video_link",
      "provider": "meeting",
      "provisioning": "immediate",
      "public_data": {}
    }
  ]
}
```

Rules:

- the top-level value is an object;
- `access`, when present, is an array of objects;
- every entry has one non-empty, trimmed, unique `key`;
- `kind` is one of Delivery's `AccessKind` values;
- `provider`, when present, is a non-empty, trimmed provider key;
- `provisioning` is `immediate` or `manual` and defaults to `immediate`;
- `public_data` is an object and defaults to `{}`;
- immediate static access (no provider) must contain non-empty `public_data`.

`parse_delivery_policy(...)` is the canonical Python parser for import/admin/configuration
boundaries. A boundary that knows the installed provider registry must pass
`known_provider_keys=...`; unknown provider keys are then rejected before an OfferingVersion is
persisted.

Migration `027-reservation-access-delivery.sql` independently enforces every provider-independent
rule above on `offering_versions`. This is intentional defense in depth for direct SQL/import paths.
A deployment-specific provider registry is application configuration, not PostgreSQL catalog truth,
so the database checks provider-key shape but does not pretend to know which adapters are installed.

The current Product/Catalog HTTP API remains query-oriented and does **not** expose OfferingVersion
creation/versioning. PR #49 therefore establishes the authoritative Delivery policy contract and
runtime, but does not claim a complete product-facing authoring workflow. Any future Catalog/admin
command that creates an OfferingVersion with Delivery access must invoke the canonical parser with
its configured provider registry before persistence; raw application SQL is not an approved
production authoring surface.

As an additional runtime defense, `ReservationAccessService` validates duplicate keys, static
immediate content, and provider registration before it revokes or creates any `ReservationAccess`
row. This protects against corrupted/bypassed configuration without making runtime validation the
primary authoring boundary.

## Database and worker authority

`request_engine_worker` owns only the Outbox control-plane lease. It has no SELECT/DML authority on
`request_engine.reservation_access` and does not receive its read view.

Delivery repositories are constructed from `domain_session_factory` and authenticate through the
`request_engine_app` role. READY and REVOKED transitions validate the current Outbox `claim_token`
inside the same app transaction through `request_cmd.lock_outbox_message_claim(...)`.

The Outbox token is a technical capability. It is passed only to explicitly fenced internal
handlers and is never added to the published `OutboxEvent`.

## Provider I/O and crash recovery

Provider/network I/O never runs while authoritative database locks are held.

Each access row is scoped to:

```text
organization + reservation + reservation_revision + access_key
```

and has a stable provider identity:

```text
reservation-access:{reservation_id}:{access_key}:r{reservation_revision}
```

The `materialization_key` persisted on the `pending` claim is the identity passed to every provider
operation. The service does not recalculate a second provider identity after the claim exists.

Provider adapters must make `provision` semantically idempotent by that key, expose a non-creating
`lookup` operation, and make `revoke` idempotent. For provider-backed pending access with no local
provider evidence, reconciliation is exactly:

```text
lookup(materialization_key)
    |-- found  -> reuse returned evidence
    `-- absent -> provision(materialization_key, ...)
```

If `lookup` fails, `provision` is not attempted in that reconciliation attempt. `provision`
idempotency remains a second line of defense rather than the only crash-window guarantee.

`pending` is recovery evidence, not usable access authority. In the crash window
`provider succeeds -> process dies before DB evidence`, a later claimant performs the non-creating
lookup first and reuses the existing artifact instead of blindly provisioning again. A stale process
may still record provider evidence after it loses its Outbox lease so a new claimant can recover.
Only a holder of the current Outbox lease can publish `ready` or `revoked`.

A reschedule creates access for the new Reservation revision only after older unrevoked revisions
are reconciled/revoked. Old rows are retained as audit/recovery evidence rather than overwritten.
A stale Reservation revision is rejected before it can revoke current access.

## Read surface

`request_read.reservation_access_v1` is an internal app/admin projection. Access URIs can be bearer
credentials, so this change does not create a public HTTP endpoint. Any future caller-facing read
capability must reuse Reservation Party authority and explicitly constrain which access fields are
returned.
