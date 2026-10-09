"""Add notified columns to memberships

Revision ID: 0132aeb12a1c
Revises: n0j1e2f3g4h5
Create Date: 2026-10-08 22:12:26.046277

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0132aeb12a1c'
down_revision: Union[str, Sequence[str], None] = 'n0j1e2f3g4h5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('memberships', sa.Column('notified_3d', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('memberships', sa.Column('notified_24h', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('memberships', 'notified_24h')
    op.drop_column('memberships', 'notified_3d')
