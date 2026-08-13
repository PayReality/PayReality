"""enterprise surface isolation

Revision ID: c3f8a1b2d5e9
Revises: a7d3e9f2c6b1
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1b2d5e9'
down_revision: Union[str, Sequence[str], None] = 'a7d3e9f2c6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_VALUES = "'owner','governance_admin','agent_admin','reviewer','auditor','executive'"


def upgrade() -> None:
    """Upgrade schema.

    Milestone 3 (Enterprise Surface Isolation,
    MILESTONE_3_ENTERPRISE_SURFACE_ISOLATION_SUMMARY.md): three
    independent additions, all additive/nullable-first per this
    codebase's established convention (Milestone 1's authority_corpora/
    evidence/principals migrations, Milestone 2's own migration):

    1. `policy_extraction_uploads.organization_id` -- the single-document
       AI Policy Builder pipeline had no organization concept at all
       (confirmed in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md).
       `policy_extraction_candidates` deliberately does NOT get its own
       organization_id column: a candidate always resolves its
       organization via exactly one of upload_id -> this new column, or
       corpus_id -> authority_corpora.organization_id (Milestone 1),
       mirroring the same "resolve through the parent, never duplicate
       the column" choice already made for every other corpus-scoped
       extraction table.
    2. `organizations.status`/`deactivated_at`/`deactivated_by`/
       `archived_at`/`archived_by` -- the Organization Lifecycle
       (create/deactivate/archive) this milestone introduces. Backfilled
       to 'active' for every pre-existing row -- the only correct value,
       since nothing before this migration could deactivate or archive
       an Organization at all.
    3. `organization_invitations` -- a new table, so its FK is NOT NULL
       from the start (no pre-existing rows to backfill against), unlike
       every additive organization_id column elsewhere in this codebase.
       token_hash follows the exact SHA-256-of-a-high-entropy-secret
       pattern api_keys.key_hash already established (see
       auth_service.hash_api_key's own docstring for why bcrypt is the
       wrong tool for a generated, not human-chosen, secret).
    """
    op.add_column(
        "policy_extraction_uploads",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_policy_extraction_uploads_organization_id",
        "policy_extraction_uploads", "organizations", ["organization_id"], ["id"],
    )
    op.create_index(
        "idx_policy_extraction_uploads_organization", "policy_extraction_uploads", ["organization_id"]
    )
    op.execute(
        "UPDATE policy_extraction_uploads SET organization_id = "
        "(SELECT id FROM organizations ORDER BY created_at ASC LIMIT 1) "
        "WHERE organization_id IS NULL"
    )

    op.add_column(
        "organizations",
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column("organizations", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("deactivated_by", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("archived_by", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_organizations_status", "organizations", "status IN ('active','deactivated','archived')"
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"), nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("invited_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_organization_invitations_role"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','revoked','expired')",
            name="ck_organization_invitations_status",
        ),
        sa.UniqueConstraint("token_hash", name="uq_organization_invitations_token_hash"),
    )
    op.create_index(
        "idx_organization_invitations_organization", "organization_invitations", ["organization_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_organization_invitations_organization", table_name="organization_invitations")
    op.drop_table("organization_invitations")

    op.drop_constraint("ck_organizations_status", "organizations", type_="check")
    op.drop_column("organizations", "archived_by")
    op.drop_column("organizations", "archived_at")
    op.drop_column("organizations", "deactivated_by")
    op.drop_column("organizations", "deactivated_at")
    op.drop_column("organizations", "status")

    op.drop_index("idx_policy_extraction_uploads_organization", table_name="policy_extraction_uploads")
    op.drop_constraint(
        "fk_policy_extraction_uploads_organization_id", "policy_extraction_uploads", type_="foreignkey"
    )
    op.drop_column("policy_extraction_uploads", "organization_id")
