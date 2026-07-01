"""audit_log append-only enforcement (Postgres trigger)

Revision ID: 0002_audit_append_only
Revises: 0001_initial
Create Date: 2026-06-30

Blocks UPDATE/DELETE on audit_log at the database level so the audit trail is
tamper-evident even if application code is compromised. No-op on non-Postgres
(e.g. the SQLite test DB), where the app-level append-only discipline applies.
"""
from alembic import op

revision = "0002_audit_append_only"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only; % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable();")
