"""trusted integration architecture phase 1: integration contract kernel

Revision ID: c0eb613b4169
Revises: 741abf7b0146
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c0eb613b4169'
down_revision: Union[str, Sequence[str], None] = '741abf7b0146'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Trusted Integration Architecture, Phase 1 (TRUSTED_INTEGRATION_
    ARCHITECTURE.md, Founder Decisions & Design Closure Addendum): the
    Integration Contract kernel. Two new, standalone tables. No existing
    table is touched -- Intent gains no column in this migration; that
    lands only in Phase 2, once runtime submission actually uses it.
    """
    op.create_table(
        'integrations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('external_system_label', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_integrations_organization', 'integrations', ['organization_id'])

    op.create_table(
        'integration_contract_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('integration_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('source_operation', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('canonical_action', sa.Text(), nullable=False),
        sa.Column('resource_path', sa.Text(), nullable=True),
        sa.Column('fact_subject_path', sa.Text(), nullable=True),
        sa.Column('amount_path', sa.Text(), nullable=True),
        sa.Column('currency_path', sa.Text(), nullable=True),
        sa.Column('context_bindings', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('content_hash', sa.Text(), nullable=True),
        sa.Column('source_schema_fingerprint', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='draft', nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.Text(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.CheckConstraint(
            "status IN ('draft','validated','approved','retired')",
            name='ck_integration_contract_versions_status',
        ),
        sa.UniqueConstraint(
            'integration_id', 'source_operation', 'version',
            name='uq_integration_contract_versions_identity',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_integration_contract_versions_org', 'integration_contract_versions', ['organization_id']
    )
    op.create_index(
        'idx_integration_contract_versions_lookup', 'integration_contract_versions',
        ['integration_id', 'source_operation'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_integration_contract_versions_lookup', table_name='integration_contract_versions')
    op.drop_index('idx_integration_contract_versions_org', table_name='integration_contract_versions')
    op.drop_table('integration_contract_versions')
    op.drop_index('idx_integrations_organization', table_name='integrations')
    op.drop_table('integrations')
