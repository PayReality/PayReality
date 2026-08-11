"""authority intelligence: blob_path on authority_corpus_documents

Revision ID: a1f9c3e5d7b2
Revises: d7e28b4c91a6
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f9c3e5d7b2'
down_revision: Union[str, Sequence[str], None] = 'd7e28b4c91a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Authority Intelligence Program, Phase 1: nullable, additive column
    only, no existing row changes shape and no behavior change for any
    environment that never configures Blob Storage. `content` (the
    existing LargeBinary column) keeps being written on every upload
    exactly as before; `blob_path` is set alongside it when this
    document was also written to Blob Storage."""
    op.add_column(
        'authority_corpus_documents',
        sa.Column('blob_path', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('authority_corpus_documents', 'blob_path')
