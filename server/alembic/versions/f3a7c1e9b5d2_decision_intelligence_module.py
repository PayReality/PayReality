"""decision intelligence module: workflows, cases, patterns, questions, answers, decision rules, replays, audit ledger

Revision ID: f3a7c1e9b5d2
Revises: e2c4b6d8f1a3
Create Date: 2026-10-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3a7c1e9b5d2'
down_revision: Union[str, Sequence[str], None] = 'e2c4b6d8f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Decision Intelligence (module prefix `DI`): a brand-new, fully
    isolated set of tables -- no existing table is altered, no existing
    row changes shape. Reuses `organizations`/`users` for multi-tenancy
    and authorship only, via plain foreign keys, never a shared or
    modified table.

    Table creation order matters for one circular reference:
    di_decision_rules.current_version_id points at di_rule_versions.id,
    and di_rule_versions.rule_id points back at di_decision_rules.id.
    di_decision_rules is created first without that column, then
    di_rule_versions is created, then the column + FK is added to
    di_decision_rules.
    """
    op.create_table(
        'di_workflows',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('business_context', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='active', nullable=False),
        sa.Column('owner_user_id', sa.UUID(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('active','archived')", name='ck_di_workflows_status'),
    )
    op.create_index('idx_di_workflows_organization', 'di_workflows', ['organization_id'])

    op.create_table(
        'di_cases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('external_ref', sa.Text(), nullable=True),
        sa.Column('facts', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('evidence_refs', postgresql.JSONB(), nullable=True),
        sa.Column('ai_recommendation', postgresql.JSONB(), nullable=True),
        sa.Column('human_decision', postgresql.JSONB(), nullable=True),
        sa.Column('escalation_reason', sa.Text(), nullable=True),
        sa.Column('outcome', sa.Text(), nullable=True),
        sa.Column('outcome_evidence', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='open', nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('open','resolved','escalated')", name='ck_di_cases_status'),
    )
    op.create_index('idx_di_cases_organization_workflow', 'di_cases', ['organization_id', 'workflow_id'])

    op.create_table(
        'di_patterns',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('proposed_explanation', sa.Text(), nullable=False),
        sa.Column('alternative_explanations', postgresql.JSONB(), nullable=True),
        sa.Column('confidence', sa.Text(), nullable=True),
        sa.Column('review_status', sa.Text(), server_default='proposed', nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "category IN ('missing_facts','unclear_policy','conflicting_rules','authority_gap',"
            "'context_interpretation','human_judgement','other')",
            name='ck_di_patterns_category',
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('low','medium','high')", name='ck_di_patterns_confidence'
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed','reviewed','confirmed','rejected')",
            name='ck_di_patterns_review_status',
        ),
    )
    op.create_index('idx_di_patterns_organization_workflow', 'di_patterns', ['organization_id', 'workflow_id'])

    op.create_table(
        'di_pattern_cases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('pattern_id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['pattern_id'], ['di_patterns.id']),
        sa.ForeignKeyConstraint(['case_id'], ['di_cases.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pattern_id', 'case_id', name='uq_di_pattern_cases_pattern_case'),
    )

    op.create_table(
        'di_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='proposed', nullable=False),
        sa.Column('reach_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('impact_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('risk_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('answerability_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('decision_sensitivity_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('priority_score', sa.Numeric(6, 2), nullable=True),
        sa.Column('scoring_version', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.UUID(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('proposed','in_analysis','awaiting_answer','answer_submitted','approved',"
            "'logic_drafted','logic_validated','replay_completed','ready_for_review',"
            "'approved_for_operational_use')",
            name='ck_di_questions_status',
        ),
    )
    op.create_index('idx_di_questions_organization_workflow', 'di_questions', ['organization_id', 'workflow_id'])

    op.create_table(
        'di_question_patterns',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('question_id', sa.UUID(), nullable=False),
        sa.Column('pattern_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['di_questions.id']),
        sa.ForeignKeyConstraint(['pattern_id'], ['di_patterns.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'pattern_id', name='uq_di_question_patterns_question_pattern'),
    )

    op.create_table(
        'di_question_cases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('question_id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['di_questions.id']),
        sa.ForeignKeyConstraint(['case_id'], ['di_cases.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'case_id', name='uq_di_question_cases_question_case'),
    )

    op.create_table(
        'di_answers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('question_id', sa.UUID(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('evidence_refs', postgresql.JSONB(), nullable=True),
        sa.Column('scope', sa.Text(), nullable=True),
        sa.Column('conditions_exceptions', sa.Text(), nullable=True),
        sa.Column('effective_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('previous_version_id', sa.UUID(), nullable=True),
        sa.Column('author_user_id', sa.UUID(), nullable=False),
        sa.Column('approver_user_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.Text(), server_default='draft', nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['di_questions.id']),
        sa.ForeignKeyConstraint(['previous_version_id'], ['di_answers.id']),
        sa.ForeignKeyConstraint(['author_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approver_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('draft','submitted','under_review','approved','rejected','superseded')",
            name='ck_di_answers_status',
        ),
    )
    op.create_index('idx_di_answers_question', 'di_answers', ['question_id'])

    # di_decision_rules created WITHOUT current_version_id -- its target
    # table (di_rule_versions) doesn't exist yet. Added back below.
    op.create_table(
        'di_decision_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('source_answer_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.Text(), server_default='draft', nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['source_answer_id'], ['di_answers.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('draft','validated')", name='ck_di_decision_rules_status'),
    )
    op.create_index(
        'idx_di_decision_rules_organization_workflow', 'di_decision_rules', ['organization_id', 'workflow_id']
    )

    op.create_table(
        'di_rule_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('schema_json', postgresql.JSONB(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['di_decision_rules.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rule_id', 'version', name='uq_di_rule_versions_rule_version'),
    )
    op.create_index('idx_di_rule_versions_rule', 'di_rule_versions', ['rule_id'])

    # batch_alter_table (rather than plain add_column/create_foreign_key):
    # identical, single ALTER TABLE statements on Postgres (the real
    # target), but also makes this portable to a SQLite-backed dev/test
    # database, which cannot ALTER a table to add a foreign key
    # constraint outside of batch mode's copy-and-move strategy.
    with op.batch_alter_table('di_decision_rules') as batch_op:
        batch_op.add_column(sa.Column('current_version_id', sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            'fk_di_decision_rules_current_version_id', 'di_rule_versions', ['current_version_id'], ['id'],
        )

    op.create_table(
        'di_replay_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('rule_version_id', sa.UUID(), nullable=False),
        sa.Column('case_set_definition', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary', postgresql.JSONB(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['di_workflows.id']),
        sa.ForeignKeyConstraint(['rule_version_id'], ['di_rule_versions.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name='ck_di_replay_runs_status'),
    )
    op.create_index(
        'idx_di_replay_runs_organization_workflow', 'di_replay_runs', ['organization_id', 'workflow_id']
    )

    op.create_table(
        'di_replay_case_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('replay_run_id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('baseline_decision', postgresql.JSONB(), nullable=True),
        sa.Column('proposed_decision', postgresql.JSONB(), nullable=True),
        sa.Column('matched_conditions', postgresql.JSONB(), nullable=True),
        sa.Column('unmatched_conditions', postgresql.JSONB(), nullable=True),
        sa.Column('outcome_category', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['replay_run_id'], ['di_replay_runs.id']),
        sa.ForeignKeyConstraint(['case_id'], ['di_cases.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "outcome_category IN ('agrees_with_baseline','disagrees_with_baseline',"
            "'resolved_automatically','requires_human_review','missing_data','error')",
            name='ck_di_replay_case_results_outcome_category',
        ),
    )
    op.create_index('idx_di_replay_case_results_replay_run', 'di_replay_case_results', ['replay_run_id'])

    op.create_table(
        'di_audit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('actor_user_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('previous_value', postgresql.JSONB(), nullable=True),
        sa.Column('new_value', postgresql.JSONB(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_di_audit_events_organization', 'di_audit_events', ['organization_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_di_audit_events_organization', table_name='di_audit_events')
    op.drop_table('di_audit_events')

    op.drop_index('idx_di_replay_case_results_replay_run', table_name='di_replay_case_results')
    op.drop_table('di_replay_case_results')

    op.drop_index('idx_di_replay_runs_organization_workflow', table_name='di_replay_runs')
    op.drop_table('di_replay_runs')

    with op.batch_alter_table('di_decision_rules') as batch_op:
        batch_op.drop_constraint('fk_di_decision_rules_current_version_id', type_='foreignkey')
        batch_op.drop_column('current_version_id')

    op.drop_index('idx_di_rule_versions_rule', table_name='di_rule_versions')
    op.drop_table('di_rule_versions')

    op.drop_index('idx_di_decision_rules_organization_workflow', table_name='di_decision_rules')
    op.drop_table('di_decision_rules')

    op.drop_index('idx_di_answers_question', table_name='di_answers')
    op.drop_table('di_answers')

    op.drop_table('di_question_cases')
    op.drop_table('di_question_patterns')

    op.drop_index('idx_di_questions_organization_workflow', table_name='di_questions')
    op.drop_table('di_questions')

    op.drop_table('di_pattern_cases')

    op.drop_index('idx_di_patterns_organization_workflow', table_name='di_patterns')
    op.drop_table('di_patterns')

    op.drop_index('idx_di_cases_organization_workflow', table_name='di_cases')
    op.drop_table('di_cases')

    op.drop_index('idx_di_workflows_organization', table_name='di_workflows')
    op.drop_table('di_workflows')
