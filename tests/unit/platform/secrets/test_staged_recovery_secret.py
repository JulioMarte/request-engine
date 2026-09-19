from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest

from request_engine.platform.secrets.delivery import StagedRecoverySecret

pytestmark = [pytest.mark.unit]


def test_created_flag_is_required() -> None:
    constructor = cast(Callable[..., StagedRecoverySecret], StagedRecoverySecret)

    with pytest.raises(TypeError):
        constructor(
            reference="ref",
            digest="a" * 64,
            expires_at=datetime.now(UTC),
        )


def test_created_flag_round_trips() -> None:
    staged = StagedRecoverySecret(
        reference="ref",
        digest="a" * 64,
        expires_at=datetime.now(UTC),
        created=False,
    )

    assert staged.created is False


def test_digest_validation_still_applies() -> None:
    with pytest.raises(ValueError):
        StagedRecoverySecret(
            reference="ref",
            digest="short",
            expires_at=datetime.now(UTC),
            created=True,
        )
