from uuid import uuid4

import pytest

from request_engine.platform.db.platform_principal_authority_reader import (
    materialize_platform_authority,
)
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
)


def _row(
    *,
    capability_key: str | None,
    delegable: bool = False,
    active: bool = True,
) -> dict[str, object]:
    return {
        "principal_kind": "human",
        "active": active,
        "authority_revision": 7,
        "capability_key": capability_key,
        "delegable": delegable,
    }


def test_platform_authority_materializes_only_canonical_platform_capabilities() -> None:
    principal_id = uuid4()
    snapshot = materialize_platform_authority(
        principal_id=principal_id,
        rows=[
            _row(capability_key="organization.provision", delegable=True),
            _row(capability_key="platform.principal.provision"),
        ],
    )

    assert snapshot is not None
    assert snapshot.principal_id == principal_id
    assert snapshot.principal_kind == "human"
    assert snapshot.authority_revision == 7
    assert snapshot.capabilities == frozenset(
        {"organization.provision", "platform.principal.provision"}
    )
    assert snapshot.delegable_capabilities == frozenset({"organization.provision"})


def test_inactive_platform_principal_has_no_materialized_authority() -> None:
    assert (
        materialize_platform_authority(
            principal_id=uuid4(),
            rows=[_row(capability_key="organization.provision", active=False)],
        )
        is None
    )


def test_unknown_platform_capability_fails_closed() -> None:
    with pytest.raises(
        PrincipalAuthorityMaterializationError,
        match="unknown persisted capability",
    ):
        materialize_platform_authority(
            principal_id=uuid4(),
            rows=[_row(capability_key="platform.unknown.superpower")],
        )


def test_non_platform_capability_from_platform_boundary_fails_closed() -> None:
    with pytest.raises(
        PrincipalAuthorityMaterializationError,
        match="non-platform capability returned by platform authority boundary",
    ):
        materialize_platform_authority(
            principal_id=uuid4(),
            rows=[_row(capability_key="staff.manage_authority")],
        )
