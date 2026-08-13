"""multi-tenant runtime policy foundation

Revision ID: a7d3e9f2c6b1
Revises: f1c8b3d6a4e7
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7d3e9f2c6b1'
down_revision: Union[str, Sequence[str], None] = 'f1c8b3d6a4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "policies",
    "runtime_policy_records",
    "simulation_scenarios",
    "runtime_policy_lifecycle_events",
    "policy_activation_schedules",
)


def upgrade() -> None:
    """Upgrade schema.

    Multi-Tenant Foundation (Milestone 2,
    MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md Phase B5): every
    column added here is nullable -- no existing row's meaning changes,
    and the migration itself can never fail on existing data. Every
    existing row is then backfilled to the one Organization that
    already exists in any single-tenant deployment (there is exactly
    one correct answer for "which org" today; this is lossless, not a
    judgment call). The one structural change -- widening
    idx_policies_single_active from table-wide to per-organization --
    is mathematically equivalent to the constraint it replaces for any
    deployment with exactly one organization, which is every deployment
    that could be running this migration today.
    """
    for table in _TABLES:
        op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_organization_id", table, "organizations", ["organization_id"], ["id"]
        )
        op.create_index(f"idx_{table}_organization", table, ["organization_id"])
        # Backfill every pre-existing row to the deployment's one real
        # Organization (the oldest one, matching
        # dependencies.get_current_organization's own existing
        # Operator-Key bootstrap resolution). A no-op, safely, if no
        # Organization exists yet (a brand-new, unbootstrapped
        # deployment) -- the subquery then assigns NULL, which is what
        # every row already has.
        op.execute(
            f"UPDATE {table} SET organization_id = "
            f"(SELECT id FROM organizations ORDER BY created_at ASC LIMIT 1) "
            f"WHERE organization_id IS NULL"
        )

    op.drop_index("idx_policies_single_active", table_name="policies")
    op.create_index(
        "idx_policies_single_active_per_org",
        "policies",
        ["organization_id", "status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_policies_single_active_per_org", table_name="policies")
    op.create_index(
        "idx_policies_single_active",
        "policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    for table in reversed(_TABLES):
        op.drop_index(f"idx_{table}_organization", table_name=table)
        op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
