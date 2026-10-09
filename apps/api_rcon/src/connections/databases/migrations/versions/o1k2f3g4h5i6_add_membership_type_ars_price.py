"""Store the configured membership price in Argentine peso cents."""
from alembic import op
import sqlalchemy as sa

revision = "o1k2f3g4h5i6"
down_revision = "n0j1e2f3g4h5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("membership_types", sa.Column("price_ars", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("membership_types", "price_ars")
