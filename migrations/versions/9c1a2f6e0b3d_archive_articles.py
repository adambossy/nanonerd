"""archive articles

Revision ID: 9c1a2f6e0b3d
Revises: 5c1d2e3f4a5b
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '9c1a2f6e0b3d'
down_revision = '5c1d2e3f4a5b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('articles', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('articles', 'archived_at')
