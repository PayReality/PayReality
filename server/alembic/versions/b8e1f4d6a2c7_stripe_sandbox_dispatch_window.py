"""stripe sandbox review: durable dispatch-window anchor and account binding table

Revision ID: b8e1f4d6a2c7
Revises: a2f7c4e0d8b1
Create Date: 2026-10-01 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8e1f4d6a2c7'
down_revision: Union[str, Sequence[str], None] = 'a2f7c4e0d8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A new, standalone table -- not a column added to `operations`
    (see app.db.stripe_sandbox_models's own module docstring for why: it
    keeps this addition fully isolated from an unrelated branch's own
    uncommitted changes to models.py sitting in this session's working
    directory). One row per destination_dispatch_identity, written
    exactly once by app.services.stripe_sandbox_dispatch_window_
    service.get_or_record_dispatch_window and never updated after."""
    op.create_table(
        'stripe_sandbox_dispatch_windows',
        sa.Column('destination_dispatch_identity', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bound_stripe_account_id', sa.Text(), nullable=False),
        sa.Column('first_dispatch_attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_stripe_sandbox_dispatch_windows_organization_id'),
        sa.PrimaryKeyConstraint('destination_dispatch_identity', name='pk_stripe_sandbox_dispatch_windows'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('stripe_sandbox_dispatch_windows')
