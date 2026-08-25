"""add capability tokens

Revision ID: c9d417a5e6f8
Revises: b7e2a4f93c61
Create Date: 2026-08-25 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9d417a5e6f8'
down_revision: Union[str, Sequence[str], None] = 'b7e2a4f93c61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'capability_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('decision_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('audience', sa.Text(), nullable=False),
        sa.Column('nonce', sa.Text(), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('issued_by', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nonce', name='uq_capability_tokens_nonce'),
    )
    op.create_index('idx_capability_tokens_decision', 'capability_tokens', ['decision_id'])
    op.create_index('idx_capability_tokens_organization', 'capability_tokens', ['organization_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_capability_tokens_organization', table_name='capability_tokens')
    op.drop_index('idx_capability_tokens_decision', table_name='capability_tokens')
    op.drop_table('capability_tokens')
