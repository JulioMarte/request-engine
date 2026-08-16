import pytest

from request_engine.modules.delivery.contracts.access import (
    AccessKind,
    DeliveryPolicyValidationError,
    ProvisioningMode,
    parse_delivery_policy,
)

pytestmark = pytest.mark.unit

INVALID_POLICY_CASES: tuple[tuple[object, str], ...] = (
    ({"access": {}}, "access must be an array"),
    ({"access": ["bad"]}, r"access\[0\] must be an object"),
    (
        {"access": [{"kind": "video_link", "provider": "meeting"}]},
        r"access\[0\]\.key",
    ),
    (
        {"access": [{"key": "video", "kind": "bogus", "provider": "meeting"}]},
        "unsupported value",
    ),
    (
        {
            "access": [
                {"key": "video", "kind": "video_link", "provider": "meeting"},
                {"key": "video", "kind": "phone", "provider": "meeting"},
            ]
        },
        "duplicate key",
    ),
    (
        {
            "access": [
                {
                    "key": "video",
                    "kind": "video_link",
                    "provider": "meeting",
                    "provisioning": "later",
                }
            ]
        },
        "provisioning has unsupported value",
    ),
    (
        {
            "access": [
                {
                    "key": "address",
                    "kind": "physical_location",
                    "public_data": [],
                }
            ]
        },
        "public_data must be an object",
    ),
    (
        {"access": [{"key": "address", "kind": "physical_location"}]},
        "requires non-empty public_data",
    ),
)


def test_parse_delivery_policy_returns_canonical_access_policies() -> None:
    policies = parse_delivery_policy(
        {
            "access": [
                {
                    "key": "video",
                    "kind": "video_link",
                    "provider": "meeting",
                },
                {
                    "key": "address",
                    "kind": "physical_location",
                    "public_data": {"line1": "Main 1"},
                },
            ]
        },
        known_provider_keys={"meeting"},
    )

    assert [policy.access_key for policy in policies] == ["video", "address"]
    assert policies[0].kind is AccessKind.VIDEO_LINK
    assert policies[0].provisioning_mode is ProvisioningMode.IMMEDIATE
    assert policies[1].public_data == {"line1": "Main 1"}


@pytest.mark.parametrize(("policy", "match"), INVALID_POLICY_CASES)
def test_parse_delivery_policy_rejects_malformed_policy(
    policy: object,
    match: str,
) -> None:
    with pytest.raises(DeliveryPolicyValidationError, match=match):
        parse_delivery_policy(policy, known_provider_keys={"meeting"})


def test_parse_delivery_policy_rejects_unknown_provider_at_configuration_boundary() -> None:
    with pytest.raises(DeliveryPolicyValidationError, match="not configured"):
        parse_delivery_policy(
            {
                "access": [
                    {
                        "key": "video",
                        "kind": "video_link",
                        "provider": "missing",
                    }
                ]
            },
            known_provider_keys={"meeting"},
        )
