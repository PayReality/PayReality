"""decision intelligence: evidence-linked questions, case relevance, scoring provenance, answer disposition, replay case-split

Revision ID: a1b2c3d4e5f6
Revises: ef6f724aafff
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd9f3c2a1e8b4'
down_revision: Union[str, Sequence[str], None] = 'ef6f724aafff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Entirely additive: every new column is nullable (or carries a safe
    server_default for an existing row), no existing column is altered
    or dropped, no existing row changes shape. Six changes:

    1. `di_discovery_suggestions`: candidate_explanation/alternative_
       explanations/missing_evidence/potential_impact -- the richer,
       grounded-question fields a suggestion can now carry (provider.
       CandidateQuestion/CandidatePattern's own docstrings).
    2. `di_questions`: a provenance tag per score dimension (computed/
       human/model), a priority override (score+reason+actor+time), and
       the same candidate_explanation/alternative_explanations/missing_
       evidence/potential_impact as above, copied from a suggestion at
       accept time.
    3. `di_pattern_cases` / `di_question_cases`: `kind` (supporting/
       potentially_affected/excluded/undetermined, default 'supporting'
       so every existing link keeps its original meaning) + `reason`.
    4. `di_answers`: `disposition` (the approving expert's own concluding
       judgement) + `disposition_notes`.
    5. `di_replay_runs`: `case_split` (JSONB disclosure of development vs.
       evaluation cases, snapshotted once at run creation).
    """
    op.add_column('di_discovery_suggestions', sa.Column('candidate_explanation', sa.Text(), nullable=True))
    op.add_column('di_discovery_suggestions', sa.Column('alternative_explanations', postgresql.JSONB(), nullable=True))
    op.add_column('di_discovery_suggestions', sa.Column('missing_evidence', postgresql.JSONB(), nullable=True))
    op.add_column('di_discovery_suggestions', sa.Column('potential_impact', sa.Text(), nullable=True))

    op.add_column('di_questions', sa.Column('reach_score_source', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('impact_score_source', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('risk_score_source', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('answerability_score_source', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('decision_sensitivity_score_source', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_di_questions_reach_score_source', 'di_questions',
        "reach_score_source IS NULL OR reach_score_source IN ('computed','human','model')",
    )
    op.create_check_constraint(
        'ck_di_questions_impact_score_source', 'di_questions',
        "impact_score_source IS NULL OR impact_score_source IN ('computed','human','model')",
    )
    op.create_check_constraint(
        'ck_di_questions_risk_score_source', 'di_questions',
        "risk_score_source IS NULL OR risk_score_source IN ('computed','human','model')",
    )
    op.create_check_constraint(
        'ck_di_questions_answerability_score_source', 'di_questions',
        "answerability_score_source IS NULL OR answerability_score_source IN ('computed','human','model')",
    )
    op.create_check_constraint(
        'ck_di_questions_decision_sensitivity_score_source', 'di_questions',
        "decision_sensitivity_score_source IS NULL OR decision_sensitivity_score_source "
        "IN ('computed','human','model')",
    )
    op.add_column('di_questions', sa.Column('priority_override_score', sa.Numeric(6, 2), nullable=True))
    op.add_column('di_questions', sa.Column('priority_override_reason', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('priority_overridden_by_user_id', sa.UUID(), nullable=True))
    op.add_column('di_questions', sa.Column('priority_overridden_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_di_questions_priority_overridden_by_user_id', 'di_questions', 'users',
        ['priority_overridden_by_user_id'], ['id'],
    )
    op.add_column('di_questions', sa.Column('candidate_explanation', sa.Text(), nullable=True))
    op.add_column('di_questions', sa.Column('alternative_explanations', postgresql.JSONB(), nullable=True))
    op.add_column('di_questions', sa.Column('missing_evidence', postgresql.JSONB(), nullable=True))
    op.add_column('di_questions', sa.Column('potential_impact', sa.Text(), nullable=True))

    op.add_column(
        'di_pattern_cases',
        sa.Column('kind', sa.Text(), server_default='supporting', nullable=False),
    )
    op.add_column('di_pattern_cases', sa.Column('reason', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_di_pattern_cases_kind', 'di_pattern_cases',
        "kind IN ('supporting','potentially_affected','excluded','undetermined')",
    )

    op.add_column(
        'di_question_cases',
        sa.Column('kind', sa.Text(), server_default='supporting', nullable=False),
    )
    op.add_column('di_question_cases', sa.Column('reason', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_di_question_cases_kind', 'di_question_cases',
        "kind IN ('supporting','potentially_affected','excluded','undetermined')",
    )

    op.add_column('di_answers', sa.Column('disposition', sa.Text(), nullable=True))
    op.add_column('di_answers', sa.Column('disposition_notes', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_di_answers_disposition', 'di_answers',
        "disposition IS NULL OR disposition IN ('rule_change','fact_collection_needed',"
        "'existing_rule_sufficient','data_or_technical_issue','human_judgement_required',"
        "'insufficient_evidence')",
    )

    op.add_column('di_replay_runs', sa.Column('case_split', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Reverses every object this migration created, in
    the opposite order."""
    op.drop_column('di_replay_runs', 'case_split')

    op.drop_constraint('ck_di_answers_disposition', 'di_answers', type_='check')
    op.drop_column('di_answers', 'disposition_notes')
    op.drop_column('di_answers', 'disposition')

    op.drop_constraint('ck_di_question_cases_kind', 'di_question_cases', type_='check')
    op.drop_column('di_question_cases', 'reason')
    op.drop_column('di_question_cases', 'kind')

    op.drop_constraint('ck_di_pattern_cases_kind', 'di_pattern_cases', type_='check')
    op.drop_column('di_pattern_cases', 'reason')
    op.drop_column('di_pattern_cases', 'kind')

    op.drop_column('di_questions', 'potential_impact')
    op.drop_column('di_questions', 'missing_evidence')
    op.drop_column('di_questions', 'alternative_explanations')
    op.drop_column('di_questions', 'candidate_explanation')
    op.drop_constraint(
        'fk_di_questions_priority_overridden_by_user_id', 'di_questions', type_='foreignkey'
    )
    op.drop_column('di_questions', 'priority_overridden_at')
    op.drop_column('di_questions', 'priority_overridden_by_user_id')
    op.drop_column('di_questions', 'priority_override_reason')
    op.drop_column('di_questions', 'priority_override_score')
    op.drop_constraint('ck_di_questions_decision_sensitivity_score_source', 'di_questions', type_='check')
    op.drop_constraint('ck_di_questions_answerability_score_source', 'di_questions', type_='check')
    op.drop_constraint('ck_di_questions_risk_score_source', 'di_questions', type_='check')
    op.drop_constraint('ck_di_questions_impact_score_source', 'di_questions', type_='check')
    op.drop_constraint('ck_di_questions_reach_score_source', 'di_questions', type_='check')
    op.drop_column('di_questions', 'decision_sensitivity_score_source')
    op.drop_column('di_questions', 'answerability_score_source')
    op.drop_column('di_questions', 'risk_score_source')
    op.drop_column('di_questions', 'impact_score_source')
    op.drop_column('di_questions', 'reach_score_source')

    op.drop_column('di_discovery_suggestions', 'potential_impact')
    op.drop_column('di_discovery_suggestions', 'missing_evidence')
    op.drop_column('di_discovery_suggestions', 'alternative_explanations')
    op.drop_column('di_discovery_suggestions', 'candidate_explanation')
