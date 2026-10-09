"""Identify Discord membership commands so a retry never adds days twice.

This branch originally reused n0j1e2f3g4h5, already assigned upstream to global
seeding. Keep the downstream o1/p2 revision IDs so databases at the local p2
head can merge the upstream branch without replaying their applied columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "7bd48ca30901"
down_revision = "2c236beea135"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memberships", sa.Column("creation_operation_id", sa.String(100), nullable=True))
    op.add_column("memberships", sa.Column("creation_request_hash", sa.String(64), nullable=True))
    op.create_index("ix_memberships_creation_operation_id", "memberships", ["creation_operation_id"], unique=True)


def downgrade():
    op.drop_index("ix_memberships_creation_operation_id", table_name="memberships")
    op.drop_column("memberships", "creation_request_hash")
    op.drop_column("memberships", "creation_operation_id")
