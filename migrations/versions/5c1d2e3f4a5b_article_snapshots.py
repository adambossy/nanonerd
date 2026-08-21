"""article snapshots

Revision ID: 5c1d2e3f4a5b
Revises: 136445b6d745
Create Date: 2026-08-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '5c1d2e3f4a5b'
down_revision = '136445b6d745'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'articles',
        sa.Column('snapshot_status', sa.String(length=16), nullable=False, server_default='none'),
    )
    op.add_column(
        'articles',
        sa.Column('snapshot_available', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'articles',
        sa.Column('snapshot_bytes', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'articles', sa.Column('snapshot_captured_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('articles', sa.Column('snapshot_error', sa.Text(), nullable=True))
    op.create_table(
        'article_snapshots',
        sa.Column('article_id', sa.Integer(), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['article_id'], ['articles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('article_id'),
    )


def downgrade() -> None:
    op.drop_table('article_snapshots')
    op.drop_column('articles', 'snapshot_error')
    op.drop_column('articles', 'snapshot_captured_at')
    op.drop_column('articles', 'snapshot_bytes')
    op.drop_column('articles', 'snapshot_available')
    op.drop_column('articles', 'snapshot_status')
