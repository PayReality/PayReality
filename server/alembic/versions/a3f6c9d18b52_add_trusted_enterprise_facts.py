"""add trusted enterprise facts

Revision ID: a3f6c9d18b52
Revises: ed6215ef0acc
Create Date: 2026-08-25 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f6c9d18b52'
down_revision: Union[str, Sequence[str], None] = 'ed6215ef0acc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'fact_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active','revoked')", name='ck_fact_sources_status'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_fact_sources_organization', 'fact_sources', ['organization_id'])

    op.create_table(
        'enterprise_facts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attestation_type', sa.Text(), nullable=False),
        sa.Column('signature', sa.Text(), nullable=True),
        sa.Column('key_id', sa.Text(), nullable=True),
        sa.Column('nonce', sa.Text(), nullable=False),
        sa.CheckConstraint(
            "attestation_type IN ('signed','connector_identity')",
            name='ck_enterprise_facts_attestation_type',
        ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['source_id'], ['fact_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'nonce', name='uq_enterprise_facts_source_nonce'),
    )
    op.create_index('idx_enterprise_facts_organization', 'enterprise_facts', ['organization_id'])
    op.create_index(
        'idx_enterprise_facts_lookup', 'enterprise_facts',
        ['organization_id', 'subject', 'key', 'expires_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_enterprise_facts_lookup', table_name='enterprise_facts')
    op.drop_index('idx_enterprise_facts_organization', table_name='enterprise_facts')
    op.drop_table('enterprise_facts')
    op.drop_index('idx_fact_sources_organization', table_name='fact_sources')
    op.drop_table('fact_sources')
