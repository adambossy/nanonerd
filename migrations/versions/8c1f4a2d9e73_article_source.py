"""article source provenance

Revision ID: 8c1f4a2d9e73
Revises: 136445b6d745
Create Date: 2026-08-20 21:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8c1f4a2d9e73'
down_revision = '136445b6d745'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('articles', sa.Column('source_kind', sa.String(length=16), nullable=True))
    op.add_column('articles', sa.Column('source_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('articles', 'source_url')
    op.drop_column('articles', 'source_kind')
