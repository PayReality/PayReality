"""trusted integration architecture phase 5: adapter-backed capability authorization

Revision ID: b7d3a4f0e5c2
Revises: a1f3e9c72b6d
Create Date: 2026-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3a4f0e5c2'
down_revision: Union[str, Sequence[str], None] = 'a1f3e9c72b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Trusted Integration Architecture, Phase 5: extends Capability
    Authorization to the Adapter-mediated runtime path. Five nullable,
    additive columns on `capability_tokens`, mirroring the exact same
    additive-provenance pattern Intent's own Phase 2/3 columns already
    established -- every existing Agent-direct capability, and every
    row issued before this migration, leaves all five NULL.

    `integration_identity_id`, `enforcement_binding_id`,
    `integration_contract_version_id`, and `environment` are the live
    Trusted Integration binding a capability is issued under, so a PEP
    can verify a capability was issued for the exact Runtime Connection
    it believes it is operating within (section 9). `external_operation_id`
    is the real-world business operation identity (Phase 3), preserved
    on the capability so the one-operation-one-authority invariant
    (section 11) is visible on the capability record itself, not only
    on the Intent it was issued from.

    Also adds `enforcement_assurance` to `enforcement_bindings`: a
    customer-declared (never independently verified) label of what a
    Binding's own downstream checkpoint claims to require. Two real
    values only -- ADVISORY (the default; no declared requirement) and
    CAPABILITY_REQUIRED (the customer declares their checkpoint
    requires a valid Capability). DECLARED_DECISION_CHECK, VERIFIED, and
    REGISTERED_EXTERNAL_PEP are deliberately not part of the CHECK
    constraint: this migration does not build the distinct-trusted-
    external-PEP-workload registration those levels would require, so
    no code path may ever set them (section 30/32's own instruction:
    do not fake completeness to fill an enum).
    """
    op.add_column('capability_tokens', sa.Column('integration_identity_id', sa.UUID(), nullable=True))
    op.add_column('capability_tokens', sa.Column('enforcement_binding_id', sa.UUID(), nullable=True))
    op.add_column('capability_tokens', sa.Column('integration_contract_version_id', sa.UUID(), nullable=True))
    op.add_column('capability_tokens', sa.Column('environment', sa.Text(), nullable=True))
    op.add_column('capability_tokens', sa.Column('external_operation_id', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_capability_tokens_integration_identity_id', 'capability_tokens',
        'integration_identities', ['integration_identity_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_capability_tokens_enforcement_binding_id', 'capability_tokens',
        'enforcement_bindings', ['enforcement_binding_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_capability_tokens_integration_contract_version_id', 'capability_tokens',
        'integration_contract_versions', ['integration_contract_version_id'], ['id'],
    )
    op.create_index(
        'idx_capability_tokens_enforcement_binding', 'capability_tokens', ['enforcement_binding_id'],
    )

    op.add_column(
        'enforcement_bindings',
        sa.Column('enforcement_assurance', sa.Text(), nullable=False, server_default='ADVISORY'),
    )
    op.create_check_constraint(
        'ck_enforcement_bindings_enforcement_assurance',
        'enforcement_bindings',
        "enforcement_assurance IN ('ADVISORY', 'CAPABILITY_REQUIRED')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_enforcement_bindings_enforcement_assurance', 'enforcement_bindings', type_='check')
    op.drop_column('enforcement_bindings', 'enforcement_assurance')

    op.drop_index('idx_capability_tokens_enforcement_binding', table_name='capability_tokens')
    op.drop_constraint('fk_capability_tokens_integration_contract_version_id', 'capability_tokens', type_='foreignkey')
    op.drop_constraint('fk_capability_tokens_enforcement_binding_id', 'capability_tokens', type_='foreignkey')
    op.drop_constraint('fk_capability_tokens_integration_identity_id', 'capability_tokens', type_='foreignkey')
    op.drop_column('capability_tokens', 'external_operation_id')
    op.drop_column('capability_tokens', 'environment')
    op.drop_column('capability_tokens', 'integration_contract_version_id')
    op.drop_column('capability_tokens', 'enforcement_binding_id')
    op.drop_column('capability_tokens', 'integration_identity_id')
