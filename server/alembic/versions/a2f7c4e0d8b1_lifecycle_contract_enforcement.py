"""contract-enforcement pass: lifecycle enrollment setting, evidence
acceptance policy, action-scoped business-operation identity, execution-
stage evidence snapshot

Revision ID: a2f7c4e0d8b1
Revises: d4b8f2a6c913
Create Date: 2026-09-30 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2f7c4e0d8b1'
down_revision: Union[str, Sequence[str], None] = 'd4b8f2a6c913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    A follow-up migration, not an in-place edit of d4b8f2a6c913 (whose
    deployment status is likewise not assumed here).

    1. `integration_contract_versions` gains two versioned, semantic
       settings: lifecycle_requirement ('LEGACY' default -- every
       existing row backfills to this, preserving today's optional-
       fields behaviour exactly) and destination_evidence_kind
       ('ADAPTER_OWN_OBSERVATION', the only value this platform
       implements -- see IntegrationContractVersion's own docstring).

    2. `business_operation_identities` gains `action`, widening its own
       unique constraint from (organization_id, integration_id,
       destination, business_operation_id) to include it -- closing a
       real collision risk between two unrelated action types reusing
       the same business_operation_id under the same integration/
       destination. Backfilled from each identity's own current
       Operation's Decision/Intent where one exists (the accurate,
       real historical action); a row with no current_operation_id at
       all (should not exist in practice -- current_operation_id is
       only ever left NULL transiently, inside a single still-open
       transaction) backfills to the empty string, disclosed as a
       heuristic default, not fabricated as a real action.

    3. `operation_evidence_events` gains execution_stage_at_event, a
       required column with no natural single backfill value for
       existing rows -- backfilled from each event's own Operation's
       CURRENT execution_stage, disclosed as a heuristic (the true
       historical stage at the time of that specific past event is not
       otherwise recoverable) rather than fabricated as exact.
    """
    op.add_column(
        'integration_contract_versions',
        sa.Column('lifecycle_requirement', sa.Text(), nullable=True),
    )
    op.add_column(
        'integration_contract_versions',
        sa.Column('destination_evidence_kind', sa.Text(), nullable=True),
    )
    op.execute("UPDATE integration_contract_versions SET lifecycle_requirement = 'LEGACY' WHERE lifecycle_requirement IS NULL")
    op.execute("UPDATE integration_contract_versions SET destination_evidence_kind = 'ADAPTER_OWN_OBSERVATION' WHERE destination_evidence_kind IS NULL")
    op.alter_column('integration_contract_versions', 'lifecycle_requirement', nullable=False, server_default='LEGACY')
    op.alter_column('integration_contract_versions', 'destination_evidence_kind', nullable=False, server_default='ADAPTER_OWN_OBSERVATION')
    op.create_check_constraint(
        'ck_integration_contract_versions_lifecycle_requirement', 'integration_contract_versions',
        "lifecycle_requirement IN ('LEGACY','LIFECYCLE_REQUIRED')",
    )
    op.create_check_constraint(
        'ck_integration_contract_versions_destination_evidence_kind', 'integration_contract_versions',
        "destination_evidence_kind IN ('ADAPTER_OWN_OBSERVATION')",
    )

    op.add_column('business_operation_identities', sa.Column('action', sa.Text(), nullable=True))
    op.execute("""
        UPDATE business_operation_identities boi SET action = COALESCE((
            SELECT i.action FROM operations o
            JOIN decisions d ON d.id = o.decision_id
            JOIN intents i ON i.id = d.intent_id
            WHERE o.id = boi.current_operation_id
        ), '')
    """)
    op.alter_column('business_operation_identities', 'action', nullable=False)
    op.drop_constraint('uq_business_operation_identity', 'business_operation_identities', type_='unique')
    op.create_unique_constraint(
        'uq_business_operation_identity', 'business_operation_identities',
        ['organization_id', 'integration_id', 'action', 'destination', 'business_operation_id'],
    )

    op.add_column('operation_evidence_events', sa.Column('execution_stage_at_event', sa.Text(), nullable=True))
    op.execute("""
        UPDATE operation_evidence_events e SET execution_stage_at_event = COALESCE(
            (SELECT o.execution_stage FROM operations o WHERE o.id = e.operation_id), 'CLAIMED'
        )
    """)
    op.alter_column('operation_evidence_events', 'execution_stage_at_event', nullable=False)
    op.create_check_constraint(
        'ck_operation_evidence_events_execution_stage_at_event', 'operation_evidence_events',
        "execution_stage_at_event IN ('AUTHORIZED','CLAIMED','DISPATCHED')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_operation_evidence_events_execution_stage_at_event', 'operation_evidence_events', type_='check')
    op.drop_column('operation_evidence_events', 'execution_stage_at_event')

    op.drop_constraint('uq_business_operation_identity', 'business_operation_identities', type_='unique')
    op.create_unique_constraint(
        'uq_business_operation_identity', 'business_operation_identities',
        ['organization_id', 'integration_id', 'destination', 'business_operation_id'],
    )
    op.drop_column('business_operation_identities', 'action')

    op.drop_constraint('ck_integration_contract_versions_destination_evidence_kind', 'integration_contract_versions', type_='check')
    op.drop_constraint('ck_integration_contract_versions_lifecycle_requirement', 'integration_contract_versions', type_='check')
    op.drop_column('integration_contract_versions', 'destination_evidence_kind')
    op.drop_column('integration_contract_versions', 'lifecycle_requirement')
