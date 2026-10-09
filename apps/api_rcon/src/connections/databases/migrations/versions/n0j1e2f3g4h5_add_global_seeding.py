"""Add global seeding and server_id to PlayerSession"""
import sqlalchemy as sa
from alembic import op

revision = "n0j1e2f3g4h5"
down_revision = "m9i0d1e2f3g4"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("players", sa.Column("global_seeding_seconds", sa.Integer(), server_default="0", nullable=False))
    op.add_column("players", sa.Column("global_rewarded_seconds", sa.Integer(), server_default="0", nullable=False))
    op.add_column("player_sessions", sa.Column("server_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_player_sessions_server_id", "player_sessions", "rcon_servers", ["server_id"], ["id"])

def downgrade():
    op.drop_constraint("fk_player_sessions_server_id", "player_sessions", type_="foreignkey")
    op.drop_column("player_sessions", "server_id")
    op.drop_column("players", "global_rewarded_seconds")
    op.drop_column("players", "global_seeding_seconds")
