from fastapi import FastAPI

import request_engine.modules.tenancy.api as tenancy_api
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_tenancy_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    identity_exchange_fingerprint_key: bytes | None,
) -> PartyAuthorityReader:
    reader = tenancy_api.build_party_authority_reader(session_factory)
    tenancy_api.install_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        identity_exchange_fingerprint_key=identity_exchange_fingerprint_key,
    )
    return reader
