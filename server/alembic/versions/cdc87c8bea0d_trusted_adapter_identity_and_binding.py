"""trusted integration architecture phase 2: integration identity, enforcement binding, intent provenance

Revision ID: cdc87c8bea0d
Revises: c0eb613b4169
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdc87c8bea0d'
down_revision: Union[str, Sequence[str], None] = 'c0eb613b4169'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Trusted Integration Architecture, Phase 2: IntegrationIdentity (a
    thin, separately-authenticated workload identity, never a second
    Agent model), its own certificate table (reusing Agent Certificate's
    proven rotation semantics without reusing its literal table, since
    Certificate.agent_id is NOT NULL and adding an alternate owner would
    weaken an existing, proven constraint), EnforcementBinding (the
    runtime-deployment object) and its EnforcementBindingAgent allow-
    list join table, plus four nullable, additive provenance columns on
    Intent -- every existing Agent-direct Intent, and every new one
    submitted through the unchanged POST /v1/intents, leaves all four
    NULL.
    """
    op.create_table(
        'integration_identities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='registered', nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.CheckConstraint(
            "status IN ('registered','active','suspended','revoked','retired')",
            name='ck_integration_identities_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_integration_identities_organization', 'integration_identities', ['organization_id'])

    op.create_table(
        'integration_identity_certificates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('integration_identity_id', sa.UUID(), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['integration_identity_id'], ['integration_identities.id']),
        sa.CheckConstraint(
            "status IN ('issued','active','rotated','expired','revoked')",
            name='ck_integration_identity_certificates_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_integration_identity_certificates_identity', 'integration_identity_certificates',
        ['integration_identity_id'],
    )
    op.create_index(
        'idx_integration_identity_certificates_single_active', 'integration_identity_certificates',
        ['integration_identity_id'], unique=True, postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        'enforcement_bindings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('integration_identity_id', sa.UUID(), nullable=False),
        sa.Column('integration_contract_version_id', sa.UUID(), nullable=False),
        sa.Column('integration_id', sa.UUID(), nullable=False),
        sa.Column('source_operation', sa.Text(), nullable=False),
        sa.Column('environment', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='draft', nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['integration_identity_id'], ['integration_identities.id']),
        sa.ForeignKeyConstraint(['integration_contract_version_id'], ['integration_contract_versions.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id']),
        sa.CheckConstraint("status IN ('draft','active','retired')", name='ck_enforcement_bindings_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_enforcement_bindings_organization', 'enforcement_bindings', ['organization_id'])
    op.create_index(
        'idx_enforcement_bindings_single_active_per_scope', 'enforcement_bindings',
        ['integration_identity_id', 'integration_id', 'source_operation', 'environment'],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        'enforcement_binding_agents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('enforcement_binding_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['enforcement_binding_id'], ['enforcement_bindings.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.UniqueConstraint(
            'enforcement_binding_id', 'agent_id', name='uq_enforcement_binding_agents_membership',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_enforcement_binding_agents_binding', 'enforcement_binding_agents', ['enforcement_binding_id'],
    )

    op.add_column('intents', sa.Column('integration_identity_id', sa.UUID(), nullable=True))
    op.add_column('intents', sa.Column('enforcement_binding_id', sa.UUID(), nullable=True))
    op.add_column('intents', sa.Column('integration_contract_version_id', sa.UUID(), nullable=True))
    op.add_column('intents', sa.Column('environment', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_intents_integration_identity_id', 'intents', 'integration_identities',
        ['integration_identity_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_intents_enforcement_binding_id', 'intents', 'enforcement_bindings',
        ['enforcement_binding_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_intents_integration_contract_version_id', 'intents', 'integration_contract_versions',
        ['integration_contract_version_id'], ['id'],
    )
    op.create_index(
        'idx_intents_integration_identity_nonce', 'intents', ['integration_identity_id', 'nonce'],
        unique=True, postgresql_where=sa.text('integration_identity_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_intents_integration_identity_nonce', table_name='intents')
    op.drop_constraint('fk_intents_integration_contract_version_id', 'intents', type_='foreignkey')
    op.drop_constraint('fk_intents_enforcement_binding_id', 'intents', type_='foreignkey')
    op.drop_constraint('fk_intents_integration_identity_id', 'intents', type_='foreignkey')
    op.drop_column('intents', 'environment')
    op.drop_column('intents', 'integration_contract_version_id')
    op.drop_column('intents', 'enforcement_binding_id')
    op.drop_column('intents', 'integration_identity_id')

    op.drop_index('idx_enforcement_binding_agents_binding', table_name='enforcement_binding_agents')
    op.drop_table('enforcement_binding_agents')

    op.drop_index('idx_enforcement_bindings_single_active_per_scope', table_name='enforcement_bindings')
    op.drop_index('idx_enforcement_bindings_organization', table_name='enforcement_bindings')
    op.drop_table('enforcement_bindings')

    op.drop_index(
        'idx_integration_identity_certificates_single_active', table_name='integration_identity_certificates',
    )
    op.drop_index('idx_integration_identity_certificates_identity', table_name='integration_identity_certificates')
    op.drop_table('integration_identity_certificates')

    op.drop_index('idx_integration_identities_organization', table_name='integration_identities')
    op.drop_table('integration_identities')
