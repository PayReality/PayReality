"""decision intelligence: csv import jobs, configurable scoring config, case search index

Revision ID: d138b47af108
Revises: f3a7c1e9b5d2
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd138b47af108'
down_revision: Union[str, Sequence[str], None] = 'f3a7c1e9b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Three independent additions for Decision Intelligence's four new
    features (brand-new tables/indexes only -- no existing DI table is
    altered, no existing row changes shape):

    1. `di_import_jobs` (Feature: CSV case import).
    2. `di_scoring_configs` (Feature: configurable scoring weights), one
       row per organization.
    3. A `pg_trgm`-backed GIN index on `di_cases.facts::text` and on
       `di_cases.external_ref` (Feature: server-side case search) so the
       new `q` search parameter's `ILIKE '%...%'` queries are real,
       indexed lookups, not sequential scans, even though the query
       itself stays the simple ILIKE form the feature's own brief called
       "an acceptable, simple approach" for this product's documented
       demo-scale assumptions. `pg_trgm` is a standard, bundled Postgres
       contrib extension (confirmed available in the `postgres:16-alpine`
       image this repo's own `docker compose up -d postgres` already
       runs); `CREATE EXTENSION IF NOT EXISTS` is idempotent and safe to
       run against a database that already has it.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        'di_import_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('total_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('valid_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('invalid_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('row_errors', postgresql.JSONB(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('pending','validating','completed','failed')", name='ck_di_import_jobs_status'
        ),
    )
    op.create_index(
        'idx_di_import_jobs_organization_workflow', 'di_import_jobs', ['organization_id', 'workflow_id']
    )

    op.create_table(
        'di_scoring_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('reach_weight', sa.Numeric(5, 4), nullable=False),
        sa.Column('impact_weight', sa.Numeric(5, 4), nullable=False),
        sa.Column('risk_weight', sa.Numeric(5, 4), nullable=False),
        sa.Column('answerability_weight', sa.Numeric(5, 4), nullable=False),
        sa.Column('decision_sensitivity_weight', sa.Numeric(5, 4), nullable=False),
        sa.Column('scoring_version', sa.Text(), nullable=False),
        sa.Column('updated_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', name='uq_di_scoring_configs_organization'),
    )
    op.create_index('idx_di_scoring_configs_organization', 'di_scoring_configs', ['organization_id'])

    # Feature: server-side case search -- GIN trigram indexes so
    # `external_ref ILIKE '%...%'` and `facts::text ILIKE '%...%'`
    # (di_case_service.list_cases) are real, indexed substring searches.
    op.execute(
        "CREATE INDEX idx_di_cases_external_ref_trgm ON di_cases "
        "USING gin (external_ref gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX idx_di_cases_facts_text_trgm ON di_cases "
        "USING gin ((facts::text) gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema. `pg_trgm` itself is deliberately NOT dropped --
    it is a shared, database-wide extension another object could have
    started depending on since this migration ran, and dropping a shared
    extension on downgrade is a much riskier default than leaving an
    unused-but-harmless extension installed. Every object this migration
    itself created is dropped."""
    op.execute("DROP INDEX IF EXISTS idx_di_cases_facts_text_trgm")
    op.execute("DROP INDEX IF EXISTS idx_di_cases_external_ref_trgm")

    op.drop_index('idx_di_scoring_configs_organization', table_name='di_scoring_configs')
    op.drop_table('di_scoring_configs')

    op.drop_index('idx_di_import_jobs_organization_workflow', table_name='di_import_jobs')
    op.drop_table('di_import_jobs')
