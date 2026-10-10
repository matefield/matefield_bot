"""Retain scheduled membership periods and pending Discord deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "s5o6j7k8l9m0"
down_revision = "q3m4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memberships", sa.Column("is_scheduled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("memberships", sa.Column("discord_guild_id", sa.String(20), nullable=True))
    op.create_table(
        "membership_renewal_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("membership_id", sa.Integer(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("previous_membership_id", sa.Integer(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("phase", sa.String(5), nullable=False),
        sa.UniqueConstraint("membership_id", "phase", name="uq_membership_renewal_delivery_phase"),
        sa.Column("guild_id", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(20), nullable=False),
        sa.Column("user_id", sa.String(20), nullable=False),
        sa.Column("role_ids_to_add_json", sa.Text(), nullable=False),
        sa.Column("role_ids_to_remove_json", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated", sa.Boolean(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_membership_renewal_deliveries_membership_id", "membership_renewal_deliveries", ["membership_id"])
    op.create_index("ix_membership_renewal_deliveries_guild_id", "membership_renewal_deliveries", ["guild_id"])


def downgrade():
    op.drop_table("membership_renewal_deliveries")
    op.drop_column("memberships", "discord_guild_id")
    op.drop_column("memberships", "is_scheduled")
