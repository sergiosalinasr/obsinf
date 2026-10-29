"""seed oracle technology

Revision ID: ab73c2169e40
Revises: 6ef2bd813ac0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab73c2169e40"
down_revision: Union[str, Sequence[str], None] = "6ef2bd813ac0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No se asume un ID ni se reactiva una entrada administrada previamente.
    op.execute(sa.text("""
        INSERT INTO technologies (code, name, is_active)
        VALUES ('oracle', 'Oracle Database', true)
        ON CONFLICT (code) DO NOTHING
    """))


def downgrade() -> None:
    # Se conserva el catálogo: puede tener fuentes e historial asociados,
    # o haber existido antes de esta migración. No se borran datos de negocio.
    pass
