"""trusted integration architecture phase 3: business operation identity

Revision ID: a1f3e9c72b6d
Revises: cdc87c8bea0d
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3e9c72b6d'
down_revision: Union[str, Sequence[str], None] = 'cdc87c8bea0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Trusted Integration Architecture, Phase 3: three nullable, additive
    columns on `intents` -- `external_operation_id` (the stable,
    Adapter-supplied identifier of the real external business
    operation), `integration_id` (server-derived historical provenance,
    never caller-chosen, copied from the resolved Contract version at
    submission time), and `canonical_operation_fingerprint` (the
    authority-relevant meaning snapshot used only to detect a genuine
    conflict on a retry sharing the same external_operation_id) -- plus
    the real, DB-enforced "at most one committed business operation per
    (integration, environment, external_operation_id)" invariant. Every
    existing Agent-direct Intent, and every pre-Phase-3 Adapter-mediated
    one, leaves all three columns NULL.
    """
    op.add_column('intents', sa.Column('external_operation_id', sa.Text(), nullable=True))
    op.add_column('intents', sa.Column('integration_id', sa.UUID(), nullable=True))
    op.add_column('intents', sa.Column('canonical_operation_fingerprint', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_intents_integration_id', 'intents', 'integrations', ['integration_id'], ['id'],
    )
    op.create_index(
        'idx_intents_external_operation_scope', 'intents',
        ['integration_id', 'environment', 'external_operation_id'],
        unique=True, postgresql_where=sa.text('external_operation_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_intents_external_operation_scope', table_name='intents')
    op.drop_constraint('fk_intents_integration_id', 'intents', type_='foreignkey')
    op.drop_column('intents', 'canonical_operation_fingerprint')
    op.drop_column('intents', 'integration_id')
    op.drop_column('intents', 'external_operation_id')
