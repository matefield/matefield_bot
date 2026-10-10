"""Retain membership cancellation receipts until Discord roles are removed."""
from alembic import op
import sqlalchemy as sa

revision = "q3m4h5i6j7k8"
down_revision = "p2l3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "membership_removal_operations",
        sa.Column("operation_id", sa.String(100), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("steam_id", sa.String(), sa.ForeignKey("players.steam_id"), nullable=False),
        sa.Column("guild_id", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(20), nullable=False),
        sa.Column("user_id", sa.String(20), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("discord_roles_removed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_membership_removal_operations_steam_id", "membership_removal_operations", ["steam_id"])


def downgrade():
    op.drop_table("membership_removal_operations")
