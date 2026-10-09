"""audit_fixes

Revision ID: 2c236beea135
Revises: a82b4eba14e5
Create Date: 2026-10-04 00:47:49.897573

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c236beea135'
down_revision: str | Sequence[str] | None = 'a82b4eba14e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. LIMPIEZA DE STEAM IDs CORRUPTOS
    op.execute("DELETE FROM player_roles WHERE steam_id != UPPER(TRIM(steam_id))")
    op.execute("DELETE FROM player_sessions WHERE steam_id != UPPER(TRIM(steam_id))")
    op.execute("DELETE FROM memberships WHERE steam_id != UPPER(TRIM(steam_id))")
    op.execute("DELETE FROM reward_claims WHERE steam_id != UPPER(TRIM(steam_id))")
    op.execute("DELETE FROM players WHERE steam_id != UPPER(TRIM(steam_id))")

    # 2. LIMPIEZA DE FECHAS CORRUPTAS Y MEMBRESÍAS HISTÓRICAS
    op.execute("DELETE FROM memberships WHERE end_date IS NOT NULL AND start_date > end_date")
    # For historical memberships without an end_date, we set their end_date to their start_date to mark them as expired but keep the record
    op.execute("UPDATE memberships SET end_date = start_date WHERE is_active = false AND end_date IS NULL")

    # 3. CONVERSIÓN FINANCIERA (Flotante -> Entero Centavos)
    op.execute("""
    DO $$ 
    BEGIN
        IF EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_name='membership_types' AND column_name='price_usd' AND data_type='double precision'
        ) THEN
            ALTER TABLE membership_types ADD COLUMN price_cents INTEGER DEFAULT 0;
            UPDATE membership_types SET price_cents = CAST(price_usd * 100 AS INTEGER);
            ALTER TABLE membership_types DROP COLUMN price_usd;
            ALTER TABLE membership_types RENAME COLUMN price_cents TO price_usd;
        END IF;
    END $$;
    """)

    # 4. EXPANSIÓN DE LÍMITES DE TEXTO (bot_config)
    op.execute("ALTER TABLE bot_config ALTER COLUMN config_value TYPE TEXT")

    # 5. RESTRICCIONES DE INTEGRIDAD ESTRICTAS (Check Constraints)
    op.execute("""
    DO $$ 
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_player_points_positive') THEN
            ALTER TABLE players ADD CONSTRAINT check_player_points_positive CHECK (reward_points >= 0);
        END IF;
    END $$;
    """)
    op.execute("""
    DO $$ 
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_claim_points_positive') THEN
            ALTER TABLE reward_claims ADD CONSTRAINT check_claim_points_positive CHECK (points_spent >= 0);
        END IF;
    END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE reward_claims DROP CONSTRAINT check_claim_points_positive")
    op.execute("ALTER TABLE players DROP CONSTRAINT check_player_points_positive")
    op.execute("ALTER TABLE bot_config ALTER COLUMN config_value TYPE VARCHAR(255)")
    
    op.execute("ALTER TABLE membership_types ADD COLUMN price_float DOUBLE PRECISION DEFAULT 0.0")
    op.execute("UPDATE membership_types SET price_float = CAST(price_usd AS DOUBLE PRECISION) / 100.0")
    op.execute("ALTER TABLE membership_types DROP COLUMN price_usd")
    op.execute("ALTER TABLE membership_types RENAME COLUMN price_float TO price_usd")
