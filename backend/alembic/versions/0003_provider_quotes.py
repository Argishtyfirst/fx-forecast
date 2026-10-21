"""provider quotes

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21 23:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('provider_quotes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('pair', sa.String(length=12), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('buy', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('sell', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('fee_fixed', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('fee_pct', sa.Float(), nullable=True),
    sa.Column('quoted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'pair', 'channel', 'fetched_at', name='uq_provider_quotes_p_pair_ch_at')
    )
    op.create_index(op.f('ix_provider_quotes_fetched_at'), 'provider_quotes', ['fetched_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_provider_quotes_fetched_at'), table_name='provider_quotes')
    op.drop_table('provider_quotes')
