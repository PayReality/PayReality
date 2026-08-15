"""policy bundle manifest

Revision ID: ed6215ef0acc
Revises: c3f8a1b2d5e9
Create Date: 2026-08-15 14:59:50.653701

Historical Policy Binding: the missing join this milestone closes.
Decision.policy_id already points to an immutable, retired-not-deleted
`policies` row (deploy_policy never mutates or deletes one, only
retires it and creates a new one); every RuntimePolicyRecord version is
already immutable too ("never mutated after creation," its own
docstring). What was never persisted is the manifest, which specific
RuntimePolicyRecord (id + version) rows were compiled together into a
given `policies` row -- already computed in memory at deploy time
(compiler_v2.compile_bundle's own PolicyBundle.manifest), discarded
once the Rego was pushed to OPA. Nullable and additive, this
codebase's established convention: every existing `policies` row
predates this column and simply has no manifest, which is honest (no
historical deploy actually computed one to backfill from), not an
error state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ed6215ef0acc'
down_revision: Union[str, Sequence[str], None] = 'c3f8a1b2d5e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "policies",
        sa.Column("bundle_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("policies", "bundle_manifest")
