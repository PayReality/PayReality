"""sandbox organization environment

Revision ID: f1a9c4e7b3d2
Revises: d4e8b1a6f2c9
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9c4e7b3d2'
down_revision: Union[str, Sequence[str], None] = 'd4e8b1a6f2c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Developer Distribution & Sandbox v1: one additive, nullable-first
    column (this codebase's established convention -- see Milestone 3's
    own `organizations.status` migration this one directly mirrors).
    'production' is the only value prior to this migration, so every
    pre-existing row backfills to it via the column's own server
    default -- the sole correct value, since nothing before this
    migration could create a sandbox Organization at all. Deliberately
    not a security boundary: tenant isolation is, and remains,
    organization_id-scoped regardless of this label.
    """
    op.add_column(
        "organizations",
        sa.Column("environment", sa.Text(), nullable=False, server_default="production"),
    )
    op.create_check_constraint(
        "ck_organizations_environment", "organizations", "environment IN ('production','sandbox')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_organizations_environment", "organizations", type_="check")
    op.drop_column("organizations", "environment")
