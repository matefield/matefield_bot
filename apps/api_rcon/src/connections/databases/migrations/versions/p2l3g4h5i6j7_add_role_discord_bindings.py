"""Configure Discord representations of logical roles independently per guild."""
from alembic import op
import sqlalchemy as sa

revision = "p2l3g4h5i6j7"
down_revision = "o1k2f3g4h5i6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "role_discord_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("guild_id", sa.String(20), nullable=False),
        sa.Column("discord_role_id", sa.String(20), nullable=False),
        sa.Column("configured_by", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "role_id", name="uq_role_discord_binding_guild_role"),
    )
    op.create_index("ix_role_discord_bindings_role_id", "role_discord_bindings", ["role_id"])
    op.create_index("ix_role_discord_bindings_guild_id", "role_discord_bindings", ["guild_id"])


def downgrade():
    op.drop_table("role_discord_bindings")
