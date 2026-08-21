"""article extraction fidelity

Revision ID: a1c7d3e90b42
Revises: 136445b6d745
Create Date: 2026-08-20 21:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c7d3e90b42'
down_revision = 'c61bc6383371'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('articles', sa.Column('fidelity_status', sa.String(length=16), nullable=True))
    op.add_column('articles', sa.Column('fidelity_score', sa.Float(), nullable=True))
    op.add_column('articles', sa.Column('fidelity_reasons', sa.Text(), nullable=True))
    op.add_column('articles', sa.Column('fidelity_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('articles', 'fidelity_checked_at')
    op.drop_column('articles', 'fidelity_reasons')
    op.drop_column('articles', 'fidelity_score')
    op.drop_column('articles', 'fidelity_status')
