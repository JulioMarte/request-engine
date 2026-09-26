"""Project governed OIDC configuration into the runtime identity authority.

Revision ID: 0093_managed_oidc_authority_projection
Revises: 0092_appointment_signing_runtime

platform_configuration_revisions remains the source of truth.  The existing
identity_authorities row is a derived compatibility/runtime projection because
IdentityBinding stores its stable authority id.  Projection happens in the same
transaction as activation/disable, so the two trust surfaces cannot commit in a
divergent state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0093_managed_oidc_authority_projection"
down_revision: str | Sequence[str] | None = "0092_appointment_signing_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION request_engine.project_managed_oidc_authority()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_issuer text;
            v_jwks_uri text;
            v_audience text;
            v_configuration_ref text;
        BEGIN
            IF NEW.configuration_kind <> 'identity.oidc'
               OR NEW.provider_kind <> 'oidc'
               OR NEW.state = OLD.state
            THEN
                RETURN NEW;
            END IF;

            v_issuer := NEW.configuration ->> 'issuer';
            v_jwks_uri := NEW.configuration ->> 'jwks_uri';
            v_audience := NEW.configuration ->> 'audience';

            IF v_issuer IS NULL OR btrim(v_issuer) = ''
               OR v_jwks_uri IS NULL OR btrim(v_jwks_uri) = ''
               OR v_audience IS NULL OR btrim(v_audience) = ''
               OR NEW.secret_binding_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'Managed OIDC configuration is malformed'
                    USING ERRCODE = '23514';
            END IF;

            v_configuration_ref := jsonb_build_object(
                'jwks_uri', v_jwks_uri,
                'audience', v_audience,
                'managed_configuration_revision', NEW.revision
            )::text;

            IF NEW.state = 'active' THEN
                INSERT INTO request_engine.identity_authorities (
                    kind,
                    issuer_or_environment,
                    status,
                    configuration_ref
                ) VALUES (
                    'oidc',
                    v_issuer,
                    'active',
                    v_configuration_ref
                )
                ON CONFLICT (kind, issuer_or_environment)
                DO UPDATE SET
                    status = 'active',
                    configuration_ref = EXCLUDED.configuration_ref,
                    revision = request_engine.identity_authorities.revision + 1;
            ELSIF OLD.state = 'active' AND NEW.state IN ('superseded', 'disabled') THEN
                -- During replacement, the old row is superseded before the new
                -- revision becomes active.  Disable only when no other active
                -- governed revision for this issuer exists at this statement.
                UPDATE request_engine.identity_authorities AS authority
                   SET status = 'disabled',
                       revision = authority.revision + 1
                 WHERE authority.kind = 'oidc'
                   AND authority.issuer_or_environment = v_issuer
                   AND authority.status = 'active'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM request_engine.platform_configuration_revisions AS cfg
                        WHERE cfg.configuration_kind = 'identity.oidc'
                          AND cfg.provider_kind = 'oidc'
                          AND cfg.state = 'active'
                          AND cfg.id <> NEW.id
                          AND cfg.configuration ->> 'issuer' = v_issuer
                   );
            END IF;

            RETURN NEW;
        END
        $function$;

        ALTER FUNCTION request_engine.project_managed_oidc_authority()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.project_managed_oidc_authority()
            FROM PUBLIC;

        CREATE TRIGGER platform_configuration_managed_oidc_projection
            AFTER UPDATE OF state
            ON request_engine.platform_configuration_revisions
            FOR EACH ROW
            EXECUTE FUNCTION request_engine.project_managed_oidc_authority();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS platform_configuration_managed_oidc_projection "
        "ON request_engine.platform_configuration_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS request_engine.project_managed_oidc_authority()")
