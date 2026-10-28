"""add finding events context

Revision ID: 6ef2bd813ac0
Revises: 2513908a8af3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6ef2bd813ac0"
down_revision: Union[str, Sequence[str], None] = "2513908a8af3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El objeto vacío identifica los hallazgos anteriores a este cambio.
    op.add_column("findings", sa.Column(
        "event_context", postgresql.JSONB(),
        server_default=sa.text("'{}'::jsonb"), nullable=False,
    ))
    op.create_check_constraint(
        op.f("ck_findings_event_context_object"), "findings",
        "jsonb_typeof(event_context) = 'object'",
    )
    op.create_table(
        "finding_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_finding_events"),
        sa.ForeignKeyConstraint(
            ["company_id", "finding_id"], ["findings.company_id", "findings.id"],
            name="fk_finding_events_company_finding",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "event_id"], ["events_normalized.company_id", "events_normalized.id"],
            name="fk_finding_events_company_event",
        ),
        sa.UniqueConstraint(
            "company_id", "finding_id", "event_id",
            name="uq_finding_events_company_finding_event",
        ),
    )
    op.create_index(
        "ix_finding_events_company_finding", "finding_events", ["company_id", "finding_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_finding_events_company_finding", table_name="finding_events")
    op.drop_table("finding_events")
    op.drop_constraint(op.f("ck_findings_event_context_object"), "findings", type_="check")
    op.drop_column("findings", "event_context")
