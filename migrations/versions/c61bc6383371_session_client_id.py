"""session client id

Revision ID: c61bc6383371
Revises: 136445b6d745
Create Date: 2026-08-20 21:12:19.999092

"""
from alembic import op
import sqlalchemy as sa


revision = 'c61bc6383371'
down_revision = '136445b6d745'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reading_sessions",
        sa.Column("client_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_reading_sessions_client_id"),
        "reading_sessions",
        ["client_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_reading_sessions_client_id"), table_name="reading_sessions")
    op.drop_column("reading_sessions", "client_id")
