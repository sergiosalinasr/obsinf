"""seed weblogic technology

Revision ID: 245cf08bec6b
Revises: 209a839939c1
Create Date: 2026-10-21 11:18:36.862071
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '245cf08bec6b'
down_revision: Union[str, Sequence[str], None] = '209a839939c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    technologies = sa.table(
        "technologies",
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
    )

    op.bulk_insert(
        technologies,
        [
            {
                "code": "weblogic",
                "name": "Oracle WebLogic Server",
                "description": (
                    "Servidor de aplicaciones. "
                    "Integración inicial mediante archivos."
                ),
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM technologies WHERE code = :code"
        ).bindparams(code="weblogic")
    )