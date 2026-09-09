"""canonical action digest

Revision ID: a7c3e5f9d2b1
Revises: f1a9c4e7b3d2
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e5f9d2b1'
down_revision: Union[str, Sequence[str], None] = 'f1a9c4e7b3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Post-audit implementation, Priority 3 (app/domain/canonical_action.py):
    two additive, nullable columns on intents -- no server default and no
    backfill, since no row before this migration ever had a canonical
    action digest computed for it at all (unlike organizations.environment,
    there is no single correct historical value to backfill to). Every
    Agent-direct Intent, and every Adapter-mediated Intent created before
    this migration, correctly stays NULL forever. Distinct from, and never
    a replacement for, the existing canonical_operation_fingerprint column
    (a narrower, different-purpose digest that already exists and is
    unaffected by this migration).
    """
    op.add_column("intents", sa.Column("canonical_action_schema_version", sa.Integer(), nullable=True))
    op.add_column("intents", sa.Column("canonical_action_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("intents", "canonical_action_digest")
    op.drop_column("intents", "canonical_action_schema_version")
