from __future__ import annotations

import argparse
import getpass
import os
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg import Connection

from request_engine.platform.security.platform_bootstrap import (
    PlatformBootstrapRejected,
    PlatformRootAlreadyExists,
    issue_platform_bootstrap_material,
    parse_platform_bootstrap_token,
    prepare_platform_root,
)

PgConnection = Connection[Any]
_NATIVE_ISSUER = "request-engine-native"
_DSN_ENV = "REQUEST_ENGINE_BOOTSTRAP_DSN"


def _connect() -> PgConnection:
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        raise RuntimeError(f"{_DSN_ENV} is required for deployment bootstrap")
    return psycopg.connect(dsn)


def _assert_no_platform_root(conn: PgConnection) -> None:
    row = conn.execute(
        "SELECT 1 FROM request_engine.principals WHERE principal_plane = 'platform' LIMIT 1"
    ).fetchone()
    if row is not None:
        raise PlatformRootAlreadyExists("initial Platform root already exists")


def _native_authority(conn: PgConnection, *, create: bool) -> UUID:
    row = conn.execute(
        """
        SELECT id, status
          FROM request_engine.identity_authorities
         WHERE kind = 'native' AND issuer_or_environment = %s
        """,
        (_NATIVE_ISSUER,),
    ).fetchone()
    if row is None and create:
        row = conn.execute(
            """
            INSERT INTO request_engine.identity_authorities (
                kind, issuer_or_environment, status
            ) VALUES ('native', %s, 'active')
            RETURNING id, status
            """,
            (_NATIVE_ISSUER,),
        ).fetchone()
    if row is None or str(row[1]) != "active":
        raise PlatformBootstrapRejected("active Native identity authority is unavailable")
    return cast(UUID, row[0])


def issue_intent(*, ttl_minutes: int, provenance: str) -> str:
    if ttl_minutes <= 0:
        raise ValueError("--ttl-minutes must be positive")
    material = issue_platform_bootstrap_material(ttl=timedelta(minutes=ttl_minutes))
    with _connect() as conn:
        _assert_no_platform_root(conn)
        authority_id = _native_authority(conn, create=True)
        conn.execute(
            """
            INSERT INTO request_engine.platform_bootstrap_intents (
                id, token_digest, token_fingerprint, provenance_reference, expires_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                material.intent_id,
                material.token_digest,
                material.token_fingerprint,
                provenance,
                material.expires_at,
            ),
        )
    return (
        f"Native authority: {authority_id}\n"
        f"Bootstrap expires: {material.expires_at.isoformat()}\n"
        f"ONE-TIME BOOTSTRAP TOKEN: {material.raw_token}"
    )


def establish_root(*, login_handle: str, raw_token: str, password: str) -> UUID:
    intent_id, token_digest = parse_platform_bootstrap_token(raw_token)
    root = prepare_platform_root(login_handle=login_handle, password=password)
    with _connect() as conn:
        authority_id = _native_authority(conn, create=False)
        row = conn.execute(
            """
            SELECT request_platform.establish_root(
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                intent_id,
                token_digest,
                authority_id,
                root.native_identity_id,
                root.login_handle,
                root.credential_id,
                root.password_verifier,
                root.principal_id,
                root.binding_id,
            ),
        ).fetchone()
        if row is None or row[0] is None:
            raise PlatformBootstrapRejected("bootstrap token is invalid, expired, or consumed")
        return cast(UUID, row[0])


def _password() -> str:
    first = getpass.getpass("New Platform Controller password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise ValueError("password confirmation does not match")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description="Request Engine deployment trust bootstrap")
    commands = parser.add_subparsers(dest="command", required=True)

    issue = commands.add_parser("issue", help="Issue one one-time root bootstrap intent")
    issue.add_argument("--ttl-minutes", type=int, default=15)
    issue.add_argument("--provenance", required=True, help="deployment/change reference")

    establish = commands.add_parser("establish", help="Consume an intent into the first root")
    establish.add_argument("--login", required=True, help="Native Platform Controller login")

    args = parser.parse_args()
    if args.command == "issue":
        print(issue_intent(ttl_minutes=args.ttl_minutes, provenance=args.provenance))
        return

    raw_token = getpass.getpass("One-time bootstrap token: ")
    principal_id = establish_root(
        login_handle=args.login,
        raw_token=raw_token,
        password=_password(),
    )
    print(f"Platform Controller established: {principal_id}")
