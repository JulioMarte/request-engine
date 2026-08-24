DISCOVERY_ROUTES = (
    (
        "discovery.mapping",
        "PUT",
        "/v1/operations/discovery/offerings/{offering_id}/classification",
    ),
    (
        "discovery.mapping_revoke",
        "POST",
        "/v1/operations/discovery/offerings/{offering_id}/classification/revoke",
    ),
    (
        "discovery.resource_public_profile",
        "PUT",
        "/v1/operations/discovery/resources/{resource_id}/public-profile",
    ),
    (
        "discovery.resource_public_profile_deactivate",
        "POST",
        "/v1/operations/discovery/resources/{resource_id}/public-profile/deactivate",
    ),
    ("discovery.publish", "POST", "/v1/operations/discovery/publications"),
    (
        "discovery.revoke",
        "POST",
        "/v1/operations/discovery/publications/{publication_id}/revoke",
    ),
)

DISCOVERY_REVISION_OWNERS = {
    "discovery.mapping": "OfferingServiceClassification.revision",
    "discovery.mapping_revoke": "OfferingServiceClassification.revision",
    "discovery.resource_public_profile": "ResourcePublicProfile.revision",
    "discovery.resource_public_profile_deactivate": "ResourcePublicProfile.revision",
    "discovery.revoke": "DiscoveryPublication.revision",
}
