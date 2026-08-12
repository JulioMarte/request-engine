# Payments module

> **V3 status: deferred/incubating. Not a baseline dependency.**

The V2 design contains useful financial distinctions such as obligations vs provider transactions/observations, corrections/reversals, allocations, refunds, disputes and reconciliation. Those distinctions remain design knowledge, but the first V3 baseline does not require the full financial domain in order to deliver business information, booking, queues, waitlists, communications and generic Requests.

Do not add dependencies from V3 baseline modules to this module during the transition.

Payments should be reactivated only around concrete product policies such as:

```text
no payment prerequisite
pay/deposit before confirmation
reserve now / pay before deadline
```

When reactivated, keep financial truth separate from reservation/execution truth and normalize provider facts rather than accepting provider payloads as generic local status mutation.

This module's presence does not require preserving every V2 payment table in the clean V3 PostgreSQL baseline.
