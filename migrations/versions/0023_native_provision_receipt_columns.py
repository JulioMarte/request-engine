"""Restrict private provisioning receipts to the columns used by the primitive."""

from alembic import op

revision: str = "0023_native_receipt_columns"
down_revision: str | None = "0022_native_provision_session"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    DO $migration$
    DECLARE definition text; marker text;
    BEGIN
        definition := pg_get_functiondef(
            'request_platform.provision_native_identity(uuid,uuid,text,uuid,text,text,text)'
            ::regprocedure);
        marker := 'SELECT * INTO retained FROM request_engine.native_identity_provision_receipts r';
        IF (length(definition)-length(replace(definition,marker,'')))/length(marker)<>1 THEN
            RAISE EXCEPTION 'Provision receipt projection anchor missing or ambiguous';
        END IF;
        EXECUTE replace(definition,marker,
            'SELECT r.actor_principal_id,r.idempotency_key_digest,r.intent_digest,'
            'r.native_identity_id,r.login_handle INTO retained '
            'FROM request_engine.native_identity_provision_receipts r');
    END $migration$;
    REVOKE SELECT,INSERT ON request_engine.native_identity_provision_receipts
        FROM request_platform_control_definer;
    GRANT SELECT(actor_principal_id,idempotency_key_digest,intent_digest,
        native_identity_id,login_handle)
        ON request_engine.native_identity_provision_receipts
        TO request_platform_control_definer;
    GRANT INSERT(actor_principal_id,idempotency_key_digest,intent_digest,
        native_identity_id,login_handle,correlation_id)
        ON request_engine.native_identity_provision_receipts
        TO request_platform_control_definer;
    """)


def downgrade() -> None:
    raise NotImplementedError("Receipt privilege narrowing requires roll-forward")
