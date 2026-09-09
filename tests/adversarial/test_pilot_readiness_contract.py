from __future__ import annotations

import pytest

from request_engine.modules.queue.api.models import JoinQueueBody
from request_engine.platform.security.capabilities import canonical_capability_keys

pytestmark = [pytest.mark.adversarial, pytest.mark.contract]


def test_party_identity_has_first_class_duplicate_resolution_capability() -> None:
    """Pilot staff must not need shadow state to reconcile duplicate Parties."""
    identity_terms = ("merge", "duplicate", "reconcile", "consolidat")
    party_capabilities = {
        key for key in canonical_capability_keys() if key.startswith(("party.", "parties."))
    }

    assert any(term in key for key in party_capabilities for term in identity_terms), (
        "No canonical Party duplicate-resolution capability is registered; "
        "a production clinic would need an external reconciliation workflow."
    )


def test_walk_in_queue_can_persist_preferred_resource() -> None:
    """A walk-in preference must be Request Engine truth, not consumer-owned state."""
    assert "preferred_resource_id" in JoinQueueBody.model_fields, (
        "JoinQueueBody cannot persist a preferred Resource. A barber/front-desk consumer "
        "would need shadow state to remember who the customer is waiting for."
    )
