"""Persist consumed Steam links to prevent reuse after unlinking."""
import sqlalchemy as sa
from alembic import op

revision = "m9i0d1e2f3g4"
down_revision = "l8h9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("steam_link_redemptions",
                    sa.Column("token_hash", sa.String(), primary_key=True),
                    sa.Column("expires_at", sa.Integer(), nullable=False))
    op.create_index("ix_steam_link_redemptions_expires_at", "steam_link_redemptions", ["expires_at"])


def downgrade():
    op.drop_table("steam_link_redemptions")
