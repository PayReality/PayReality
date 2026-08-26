"""authority graph to runtime policy compilation gate provenance

Revision ID: 39c98daa028f
Revises: b2c3d4e5f6a7
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39c98daa028f'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Additive, nullable, no backfill -- every existing RuntimePolicyRecord
    row (manually authored, or promoted before this gate existed) is
    genuinely NULL here, never retroactively attributed to a graph
    approval it wasn't actually compiled from. Set only by
    ai_policy_builder_service.promote_candidate when a corpus-scoped
    candidate's promotion was gated on a specific AuthorityGraphApproval.
    """
    op.add_column(
        'runtime_policy_records',
        sa.Column('source_graph_approval_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'runtime_policy_records_source_graph_approval_id_fkey',
        'runtime_policy_records', 'authority_graph_approvals',
        ['source_graph_approval_id'], ['id'],
    )
    op.create_index(
        'idx_runtime_policy_records_source_graph_approval',
        'runtime_policy_records', ['source_graph_approval_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_runtime_policy_records_source_graph_approval', table_name='runtime_policy_records')
    op.drop_constraint(
        'runtime_policy_records_source_graph_approval_id_fkey',
        'runtime_policy_records', type_='foreignkey',
    )
    op.drop_column('runtime_policy_records', 'source_graph_approval_id')
