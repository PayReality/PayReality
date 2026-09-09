"""post-audit implementation priority 6: reconciliation results

Revision ID: e2c4b6d8f1a3
Revises: d8e1f2a4c6b9
Create Date: 2026-09-09 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2c4b6d8f1a3'
down_revision: Union[str, Sequence[str], None] = 'd8e1f2a4c6b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Post-audit implementation, Priority 6 (app/services/
    execution_reconciliation_service.py): a new, additive table -- no
    existing table or column is modified. Append-only, mirroring
    execution_receipts's own design: re-running reconciliation for the
    same Decision after new information arrives appends a new row rather
    than rewriting a previous one.
    """
    op.create_table(
        'reconciliation_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('decision_id', sa.UUID(), nullable=False),
        sa.Column('capability_id', sa.UUID(), nullable=True),
        sa.Column('latest_execution_receipt_id', sa.UUID(), nullable=True),
        sa.Column('canonical_action_digest', sa.Text(), nullable=True),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('result_digest', sa.Text(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('evidence_id', sa.UUID(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.ForeignKeyConstraint(['capability_id'], ['capability_tokens.id']),
        sa.ForeignKeyConstraint(['latest_execution_receipt_id'], ['execution_receipts.id']),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id']),
        sa.CheckConstraint(
            "outcome IN ('MATCHED','MISMATCHED','EXECUTION_FAILED','PARTIAL','RECEIPT_MISSING','INDETERMINATE')",
            name='ck_reconciliation_results_outcome',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_reconciliation_results_organization', 'reconciliation_results', ['organization_id'])
    op.create_index('idx_reconciliation_results_decision', 'reconciliation_results', ['decision_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_reconciliation_results_decision', table_name='reconciliation_results')
    op.drop_index('idx_reconciliation_results_organization', table_name='reconciliation_results')
    op.drop_table('reconciliation_results')
