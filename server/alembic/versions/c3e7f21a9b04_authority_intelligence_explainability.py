"""authority intelligence phase 3: explainability model, coverage, conflict types, approval audit

Revision ID: c3e7f21a9b04
Revises: a1f9c3e5d7b2
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3e7f21a9b04'
down_revision: Union[str, Sequence[str], None] = 'a1f9c3e5d7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EXPLAINABILITY_TABLES = (
    'authority_principals',
    'authority_resources',
    'authority_operations',
    'authority_relationships',
    'policy_extraction_candidates',
)


def upgrade() -> None:
    """Upgrade schema.

    Authority Intelligence Program, Phase 3 (EXPLAINABILITY_MODEL.md):
    every new column is nullable/defaulted and additive -- no existing
    row changes shape, no existing query result changes, for any
    environment on any prior schema version.
    """
    for table in _EXPLAINABILITY_TABLES:
        op.add_column(table, sa.Column('clause_reference', sa.Text(), nullable=True))
        op.add_column(table, sa.Column('extraction_reasoning', sa.Text(), nullable=True))
        op.add_column(
            table,
            sa.Column('detected_assumptions', postgresql.JSONB(), nullable=False, server_default='[]'),
        )
        op.add_column(
            table,
            sa.Column('ambiguity_flags', postgresql.JSONB(), nullable=False, server_default='[]'),
        )

    op.add_column('authority_conflicts', sa.Column('conflict_type', sa.Text(), nullable=True))
    op.add_column('authority_conflicts', sa.Column('reviewer_recommendation', sa.Text(), nullable=True))
    op.create_check_constraint(
        'ck_authority_conflicts_conflict_type',
        'authority_conflicts',
        "conflict_type IS NULL OR conflict_type IN "
        "('authority','threshold','role','policy','delegation','circular_delegation')",
    )

    op.add_column('authority_corpus_documents', sa.Column('clauses_analysed', sa.Integer(), nullable=True))
    op.add_column('authority_corpus_documents', sa.Column('clauses_ignored', sa.Integer(), nullable=True))
    op.add_column('authority_corpus_documents', sa.Column('tables_extracted', sa.Integer(), nullable=True))
    op.add_column('authority_corpus_documents', sa.Column('images_skipped', sa.Integer(), nullable=True))

    op.create_table(
        'authority_graph_approvals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('corpus_id', sa.UUID(), nullable=False),
        sa.Column('reviewer', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('evidence_snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('approval_reason', sa.Text(), nullable=True),
        sa.Column('graph_hash', sa.Text(), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corpus_id'], ['authority_corpora.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('corpus_id', 'version', name='uq_authority_graph_approvals_corpus_version'),
    )
    op.create_index(
        'idx_authority_graph_approvals_corpus', 'authority_graph_approvals', ['corpus_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_authority_graph_approvals_corpus', table_name='authority_graph_approvals')
    op.drop_table('authority_graph_approvals')

    op.drop_column('authority_corpus_documents', 'images_skipped')
    op.drop_column('authority_corpus_documents', 'tables_extracted')
    op.drop_column('authority_corpus_documents', 'clauses_ignored')
    op.drop_column('authority_corpus_documents', 'clauses_analysed')

    op.drop_constraint('ck_authority_conflicts_conflict_type', 'authority_conflicts', type_='check')
    op.drop_column('authority_conflicts', 'reviewer_recommendation')
    op.drop_column('authority_conflicts', 'conflict_type')

    for table in _EXPLAINABILITY_TABLES:
        op.drop_column(table, 'ambiguity_flags')
        op.drop_column(table, 'detected_assumptions')
        op.drop_column(table, 'extraction_reasoning')
        op.drop_column(table, 'clause_reference')
