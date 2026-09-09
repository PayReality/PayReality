"""post-audit implementation priority 5: execution receipts

Revision ID: d8e1f2a4c6b9
Revises: a7c3e5f9d2b1
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e1f2a4c6b9'
down_revision: Union[str, Sequence[str], None] = 'a7c3e5f9d2b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Post-audit implementation, Priority 5 (app/domain/execution_receipt.py,
    services/execution_receipt_service.py): a new, additive table -- no
    existing table or column is modified. Append-only by design:
    uq_execution_receipts_operation_status is the real, DB-enforced
    "one row per (integration, environment, external_operation_id,
    status)" guarantee execution_receipt_service.py's own idempotency-
    vs-conflict logic relies on, not merely its own pre-check.
    """
    op.create_table(
        'execution_receipts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('integration_identity_id', sa.UUID(), nullable=False),
        sa.Column('enforcement_binding_id', sa.UUID(), nullable=False),
        sa.Column('integration_id', sa.UUID(), nullable=False),
        sa.Column('environment', sa.Text(), nullable=False),
        sa.Column('decision_id', sa.UUID(), nullable=False),
        sa.Column('capability_id', sa.UUID(), nullable=True),
        sa.Column('canonical_action_digest', sa.Text(), nullable=False),
        sa.Column('external_operation_id', sa.Text(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('receipt_digest', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evidence_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['integration_identity_id'], ['integration_identities.id']),
        sa.ForeignKeyConstraint(['enforcement_binding_id'], ['enforcement_bindings.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id']),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.ForeignKeyConstraint(['capability_id'], ['capability_tokens.id']),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id']),
        sa.CheckConstraint(
            "status IN ('ACCEPTED','SUCCEEDED','FAILED','PARTIALLY_SUCCEEDED','UNKNOWN')",
            name='ck_execution_receipts_status',
        ),
        sa.UniqueConstraint(
            'integration_id', 'environment', 'external_operation_id', 'status',
            name='uq_execution_receipts_operation_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_execution_receipts_organization', 'execution_receipts', ['organization_id'])
    op.create_index('idx_execution_receipts_decision', 'execution_receipts', ['decision_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_execution_receipts_decision', table_name='execution_receipts')
    op.drop_index('idx_execution_receipts_organization', table_name='execution_receipts')
    op.drop_table('execution_receipts')
