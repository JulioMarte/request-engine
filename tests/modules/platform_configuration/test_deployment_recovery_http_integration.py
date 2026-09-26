"""DB-backed HTTP integration coverage for governed deployment recovery.

This test intentionally exercises the composed platform-control surface rather
than calling DeploymentRecoveryService directly.  It is the acceptance seam for
secret -> governed binding -> plan -> reconcile and must keep the provider token
write-only.

The concrete fixture wiring is supplied by the platform-control integration
harness; keeping the journey here prevents service-only tests from being mistaken
for HTTP composition evidence.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_deployment_recovery_http_journey_requires_platform_control_harness() -> None:
    """Fail loudly until the DB-backed platform-control harness wires this journey.

    P7 must not claim this evidence from mocks or service-level tests.  This
    sentinel is deliberately skipped rather than providing false-positive proof;
    the next implementation step is to replace it with the repository's real
    Postgres/OpenBao-backed HTTP fixture.
    """
    pytest.skip(
        "P7 deployment-recovery HTTP acceptance requires the real DB-backed "
        "platform-control + OpenBao integration harness"
    )
