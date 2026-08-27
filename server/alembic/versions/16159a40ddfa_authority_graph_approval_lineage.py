"""authority graph approval lineage (predecessor_approval_id)

Revision ID: 16159a40ddfa
Revises: 39c98daa028f
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16159a40ddfa'
down_revision: Union[str, Sequence[str], None] = '39c98daa028f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Additive, nullable, self-referential FK, no backfill -- every
    existing AuthorityGraphApproval row (approved before this column
    existed) genuinely had no predecessor tracked at the time, and stays
    NULL rather than being guessed from version numbers retroactively.
    Only approve_graph (going forward) ever sets this, to the corpus's
    real latest approval at the moment of the new approval.
    """
    op.add_column(
        'authority_graph_approvals',
        sa.Column('predecessor_approval_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'authority_graph_approvals_predecessor_approval_id_fkey',
        'authority_graph_approvals', 'authority_graph_approvals',
        ['predecessor_approval_id'], ['id'],
    )
    op.create_index(
        'idx_authority_graph_approvals_predecessor',
        'authority_graph_approvals', ['predecessor_approval_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_authority_graph_approvals_predecessor', table_name='authority_graph_approvals')
    op.drop_constraint(
        'authority_graph_approvals_predecessor_approval_id_fkey',
        'authority_graph_approvals', type_='foreignkey',
    )
    op.drop_column('authority_graph_approvals', 'predecessor_approval_id')
