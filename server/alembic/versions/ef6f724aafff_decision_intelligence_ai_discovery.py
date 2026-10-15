"""decision intelligence: AI-assisted discovery (DIDiscoveryRun, DIDiscoverySuggestion)

Revision ID: ef6f724aafff
Revises: d138b47af108
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ef6f724aafff'
down_revision: Union[str, Sequence[str], None] = 'd138b47af108'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Feature: AI-assisted discovery of recurring uncertainty patterns and
    candidate priority questions from real case data
    (domain/decision_intelligence/ai_discovery/). Two new tables plus two
    additive, nullable columns on existing DI tables -- no existing row
    changes shape, no existing column is altered or dropped.

    1. `di_discovery_runs`: one row per `POST .../workflows/{id}/discover`
       invocation.
    2. `di_discovery_suggestions`: the candidate Pattern/Question rows a
       run proposes. `linked_pattern_id` is deliberately NOT a foreign
       key -- see the DIDiscoverySuggestion model docstring
       (app/db/models.py) for why: it may reference either a sibling
       suggestion in this same table or a real `di_patterns` row, and a
       single FK can't target two different tables. Resolved in
       application code (di_discovery_service.accept_suggestion), not at
       the database layer.
    3. `di_patterns.source_suggestion_id` / `di_questions.source_suggestion_id`:
       additive, nullable FKs back to `di_discovery_suggestions.id`, set
       exactly once when a human accepts a suggestion -- the queryable
       trace from a real, authoritative Pattern/Question back to the AI
       suggestion (if any) it came from. NULL for every Pattern/Question
       created by hand, which remains the only way either has ever been
       created before this migration.

    Table creation order matters here: `di_discovery_suggestions` must
    exist before the ALTER TABLE statements that add FKs to it from the
    pre-existing `di_patterns`/`di_questions` tables.
    """
    op.create_table(
        'di_discovery_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('provider_used', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('cases_analyzed_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "provider_used IN ('fake','claude','azure_foundry')", name='ck_di_discovery_runs_provider_used'
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')", name='ck_di_discovery_runs_status'
        ),
    )
    op.create_index(
        'idx_di_discovery_runs_organization_workflow', 'di_discovery_runs', ['organization_id', 'workflow_id']
    )

    op.create_table(
        'di_discovery_suggestions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('discovery_run_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('supporting_case_ids', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Text(), nullable=True),
        sa.Column('linked_pattern_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.Text(), server_default='suggested', nullable=False),
        sa.Column('reviewed_by_user_id', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['discovery_run_id'], ['di_discovery_runs.id']),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("kind IN ('pattern','question')", name='ck_di_discovery_suggestions_kind'),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('low','medium','high')",
            name='ck_di_discovery_suggestions_confidence',
        ),
        sa.CheckConstraint(
            "status IN ('suggested','accepted','dismissed')", name='ck_di_discovery_suggestions_status'
        ),
    )
    op.create_index('idx_di_discovery_suggestions_run', 'di_discovery_suggestions', ['discovery_run_id'])

    op.add_column('di_patterns', sa.Column('source_suggestion_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_di_patterns_source_suggestion_id', 'di_patterns', 'di_discovery_suggestions',
        ['source_suggestion_id'], ['id'],
    )

    op.add_column('di_questions', sa.Column('source_suggestion_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_di_questions_source_suggestion_id', 'di_questions', 'di_discovery_suggestions',
        ['source_suggestion_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema. Reverses every object this migration created, in
    the opposite order (drop the dependent FKs/columns before dropping
    the table they point to)."""
    op.drop_constraint('fk_di_questions_source_suggestion_id', 'di_questions', type_='foreignkey')
    op.drop_column('di_questions', 'source_suggestion_id')

    op.drop_constraint('fk_di_patterns_source_suggestion_id', 'di_patterns', type_='foreignkey')
    op.drop_column('di_patterns', 'source_suggestion_id')

    op.drop_index('idx_di_discovery_suggestions_run', table_name='di_discovery_suggestions')
    op.drop_table('di_discovery_suggestions')

    op.drop_index('idx_di_discovery_runs_organization_workflow', table_name='di_discovery_runs')
    op.drop_table('di_discovery_runs')
