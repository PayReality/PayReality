"""product lifecycle vertical slice: operations, evidence events, and destination duplicate prevention guarantees

Revision ID: a7c3e9f1b5d6
Revises: e2c4b6d8f1a3
Create Date: 2026-09-29 00:00:00.000001

Consolidation-review fix: this migration was originally authored with
down_revision = 'f3a5c7e9b1d4' (authority_extraction_safety_remediation),
a migration file that exists only as UNCOMMITTED, untracked content on a
separate, unrelated feature branch that happened to share this same local
working directory -- it was never part of this branch's own committed
history. That made alembic's own revision graph unbuildable on any real
checkout of this branch (`alembic heads`/`history`/`upgrade head` all
raised `KeyError: 'f3a5c7e9b1d4'`, confirmed directly). Re-pointed to
e2c4b6d8f1a3 (reconciliation_results), the actual committed revision the
missing file itself chained from -- a pure graph correction, zero change
to what this migration's own upgrade()/downgrade() do or assume about
prior schema state, since f3a5c7e9b1d4 was never applied to any database
this branch's own history is responsible for.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f1b5d6'
down_revision: Union[str, Sequence[str], None] = 'e2c4b6d8f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Product lifecycle vertical slice (app/services/operation_service.py),
    hardening pass included (this migration was never applied anywhere
    before the hardening review, so it is edited in place rather than
    followed by a second "alter" migration): three new, additive tables --
    no existing table or column is modified. `operations` tracks a
    real-world attempted operation separately from its (single-use,
    spent-after-one-consumption) Capability. `operation_evidence_events`
    is the full, append-only provenance log behind Operation.state's own
    current-summary value. `destination_duplicate_prevention_guarantees`
    is the one, deliberately human-documented way (besides a
    TERMINALLY_NOT_COMMITTED operation) a replacement attempt is ever
    reported safe -- see these three models' own docstrings in
    app/db/models.py for the full reasoning.
    """
    op.create_table(
        'operations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('decision_id', sa.UUID(), nullable=False),
        sa.Column('capability_id', sa.UUID(), nullable=True),
        sa.Column('material_action_digest', sa.Text(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=True),
        sa.Column('destination_operation_id', sa.Text(), nullable=True),
        sa.Column('state', sa.Text(), server_default='AUTHORIZED', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.ForeignKeyConstraint(['capability_id'], ['capability_tokens.id']),
        sa.CheckConstraint(
            "state IN ('AUTHORIZED','CLAIMED','DISPATCHED','COMMITTED','TERMINALLY_NOT_COMMITTED','OUTCOME_UNKNOWN')",
            name='ck_operations_state',
        ),
        sa.UniqueConstraint('decision_id', name='uq_operations_decision'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_operations_organization', 'operations', ['organization_id'])
    op.create_index('idx_operations_destination_operation', 'operations', ['destination_operation_id'])

    op.create_table(
        'operation_evidence_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('operation_id', sa.UUID(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('reporter_kind', sa.Text(), nullable=False),
        sa.Column('integration_identity_id', sa.UUID(), nullable=True),
        sa.Column('reported_by', sa.Text(), nullable=False),
        sa.Column('signature_verified', sa.Boolean(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=True),
        sa.Column('destination_operation_id', sa.Text(), nullable=True),
        sa.Column('claimed_status', sa.Text(), nullable=True),
        sa.Column('evidence_strength', sa.Text(), nullable=False),
        sa.Column('receipt_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id']),
        sa.ForeignKeyConstraint(['integration_identity_id'], ['integration_identities.id']),
        sa.ForeignKeyConstraint(['receipt_id'], ['execution_receipts.id']),
        sa.CheckConstraint("event_type IN ('DISPATCH_REPORTED','OBSERVATION')", name='ck_operation_evidence_events_type'),
        sa.CheckConstraint("reporter_kind IN ('SIGNED_ADAPTER_IDENTITY','RBAC_HUMAN')", name='ck_operation_evidence_events_reporter_kind'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_operation_evidence_events_organization', 'operation_evidence_events', ['organization_id'])
    op.create_index('idx_operation_evidence_events_operation', 'operation_evidence_events', ['operation_id'])

    op.create_table(
        'destination_duplicate_prevention_guarantees',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('operation_id', sa.UUID(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=False),
        sa.Column('scope_description', sa.Text(), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('documented_by', sa.Text(), nullable=False),
        sa.Column('documented_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('restricted_to_integration_identity_id', sa.UUID(), nullable=True),
        sa.Column('restricted_to_enforcement_binding_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id']),
        sa.ForeignKeyConstraint(['restricted_to_integration_identity_id'], ['integration_identities.id']),
        sa.ForeignKeyConstraint(['restricted_to_enforcement_binding_id'], ['enforcement_bindings.id']),
        sa.UniqueConstraint('operation_id', name='uq_duplicate_prevention_operation'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_duplicate_prevention_organization', 'destination_duplicate_prevention_guarantees', ['organization_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_duplicate_prevention_organization', table_name='destination_duplicate_prevention_guarantees')
    op.drop_table('destination_duplicate_prevention_guarantees')
    op.drop_index('idx_operation_evidence_events_operation', table_name='operation_evidence_events')
    op.drop_index('idx_operation_evidence_events_organization', table_name='operation_evidence_events')
    op.drop_table('operation_evidence_events')
    op.drop_index('idx_operations_destination_operation', table_name='operations')
    op.drop_index('idx_operations_organization', table_name='operations')
    op.drop_table('operations')
