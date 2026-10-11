"""Merge guild-aware membership delivery with upstream squads and seeding.

Existing databases at either p2l3g4h5i6j7 or 0132aeb12a1c apply only the other
branch, preserving the already-applied migration history on both sides.
"""

revision = "29f437dc92a1"
down_revision = ("p2l3g4h5i6j7", "0132aeb12a1c")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
