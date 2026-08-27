"""evidence hash-chain sequence ordinal (G01 chain-ordering follow-up)

Revision ID: 741abf7b0146
Revises: 16159a40ddfa
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '741abf7b0146'
down_revision: Union[str, Sequence[str], None] = '16159a40ddfa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Additive, nullable, no backfill: every existing Evidence row genuinely
    has no recorded write-ordinal (the concept didn't exist when it was
    written), and stays NULL rather than having a fabricated order
    guessed from created_at/id after the fact. Only
    services/intent_service.py's append_evidence sets this, going
    forward, under the same per-organization row lock (G01) that now
    serializes concurrent appends -- so it is always assigned race-safely.
    """
    op.add_column('evidence', sa.Column('sequence', sa.BigInteger(), nullable=True))
    op.create_index(
        'idx_evidence_organization_sequence', 'evidence', ['organization_id', 'sequence'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_evidence_organization_sequence', table_name='evidence')
    op.drop_column('evidence', 'sequence')
