"""closeout pass: business operation identity, execution stage / outcome
status split, and evidence acceptance rules

Revision ID: d4b8f2a6c913
Revises: a7c3e9f1b5d6
Create Date: 2026-09-29 00:00:02.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b8f2a6c913'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f1b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    A FOLLOW-UP migration, deliberately, rather than an in-place edit of
    a7c3e9f1b5d6 -- this closeout pass starts from a branch that was
    already committed once (product-lifecycle-hardening), and section 4
    of the review that requested this pass explicitly instructs against
    rewriting a migration whose deployment status is not established
    with certainty. a7c3e9f1b5d6 itself was still safe to edit in place
    (never applied anywhere before that edit); this one is not assumed
    to be, so it is left untouched.

    Three real, additive/alter changes:

    1. `intents` gains business_operation_id / intended_destination
       (both nullable) -- section 1's own business-operation identity,
       DISTINCT from the pre-existing external_operation_id/integration_id
       idempotency scope (see BusinessOperationIdentity's own docstring,
       app/db/models.py, for why these cannot be the same field).

    2. New table `business_operation_identities` -- the identity itself.
       Its own current_operation_id -> operations.id foreign key is
       added via a SEPARATE op.create_foreign_key call after `operations`
       has its new columns (not because of an ordering requirement at
       the SQL level -- `operations` already exists from a7c3e9f1b5d6 --
       but to keep this migration's own two new-table/altered-table
       sections independently readable).

    3. `operations` gains business_operation_identity_id / integration_id
       / integration_contract_version_id / previous_attempt_operation_id
       (section 1), and its old single `state` column is replaced by
       three: execution_stage, outcome_status, evidence_assurance
       (section 3 -- execution stage and outcome certainty are
       independent facts; section 2 -- what kind of evidence
       outcome_status actually rests on). This table has never been
       populated by any real production code path (create_operation_for_
       decision has zero real router call sites as of this migration --
       confirmed by direct grep, not assumed), so the backfill below is
       a defensive, disclosed best-effort for any row that DOES exist
       (e.g. from a prior test run against a real database), not a
       claim that it perfectly reconstructs history no data exists to
       reconstruct.

    4. `operation_evidence_events` gains reconciliation_outcome /
       rationale / evidence_reference_ids, and its event_type /
       reporter_kind CHECK constraints widen to include
       OBSERVATION_CONFLICT_REJECTED and MANUAL_ADJUDICATION.
    """
    # --- 1. intents: business-operation identity fields ---------------
    op.add_column('intents', sa.Column('business_operation_id', sa.Text(), nullable=True))
    op.add_column('intents', sa.Column('intended_destination', sa.Text(), nullable=True))

    # --- 2. business_operation_identities (new table) ------------------
    op.create_table(
        'business_operation_identities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('integration_id', sa.UUID(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=False),
        sa.Column('business_operation_id', sa.Text(), nullable=False),
        sa.Column('current_operation_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id']),
        sa.UniqueConstraint(
            'organization_id', 'integration_id', 'destination', 'business_operation_id',
            name='uq_business_operation_identity',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_business_operation_identities_organization', 'business_operation_identities', ['organization_id'])

    # --- 3. operations: identity linkage + execution_stage/outcome_status/evidence_assurance split ---
    op.add_column('operations', sa.Column('business_operation_identity_id', sa.UUID(), nullable=True))
    op.add_column('operations', sa.Column('integration_id', sa.UUID(), nullable=True))
    op.add_column('operations', sa.Column('integration_contract_version_id', sa.UUID(), nullable=True))
    op.add_column('operations', sa.Column('previous_attempt_operation_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_operations_business_operation_identity', 'operations', 'business_operation_identities',
        ['business_operation_identity_id'], ['id'],
    )
    op.create_foreign_key('fk_operations_integration', 'operations', 'integrations', ['integration_id'], ['id'])
    op.create_foreign_key(
        'fk_operations_integration_contract_version', 'operations', 'integration_contract_versions',
        ['integration_contract_version_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_operations_previous_attempt', 'operations', 'operations',
        ['previous_attempt_operation_id'], ['id'],
    )
    op.create_index('idx_operations_business_identity', 'operations', ['business_operation_identity_id'])

    # Now the FK business_operation_identities.current_operation_id can
    # be added -- both tables exist with their final column sets.
    op.create_foreign_key(
        'fk_boi_current_operation', 'business_operation_identities', 'operations',
        ['current_operation_id'], ['id'],
    )

    op.add_column('operations', sa.Column('execution_stage', sa.Text(), nullable=True))
    op.add_column('operations', sa.Column('outcome_status', sa.Text(), nullable=True))
    op.add_column('operations', sa.Column('evidence_assurance', sa.Text(), nullable=True))

    # Defensive, disclosed best-effort backfill -- see this function's
    # own docstring for why no row is expected to exist in practice.
    # execution_stage: AUTHORIZED/CLAIMED map directly; every other old
    # `state` value could only have been reached via DISPATCHED or
    # CLAIMED under the pre-split design, and which one is no longer
    # reconstructable from `state` alone -- DISPATCHED is the more
    # common real path (a claim with genuine dispatch evidence) and is
    # used here, disclosed as a heuristic, not a certainty.
    op.execute("""
        UPDATE operations SET execution_stage = CASE
            WHEN state = 'AUTHORIZED' THEN 'AUTHORIZED'
            WHEN state = 'CLAIMED' THEN 'CLAIMED'
            ELSE 'DISPATCHED'
        END
    """)
    op.execute("""
        UPDATE operations SET outcome_status = CASE
            WHEN state = 'COMMITTED' THEN 'COMMITTED'
            WHEN state = 'TERMINALLY_NOT_COMMITTED' THEN 'TERMINALLY_NOT_COMMITTED'
            ELSE 'UNKNOWN'
        END
    """)
    # evidence_assurance cannot be reconstructed from `state` alone
    # (the pre-section-2 code let either reporter kind reach a terminal
    # state) -- NONE for a still-open operation, REPORTED_UNVERIFIED for
    # a pre-existing terminal one is the conservative choice (it does
    # NOT claim ADAPTER_REPORTED assurance the historical row cannot
    # prove it had).
    op.execute("""
        UPDATE operations SET evidence_assurance = CASE
            WHEN outcome_status IN ('COMMITTED', 'TERMINALLY_NOT_COMMITTED') THEN 'REPORTED_UNVERIFIED'
            ELSE 'NONE'
        END
    """)

    op.alter_column('operations', 'execution_stage', nullable=False, server_default='AUTHORIZED')
    op.alter_column('operations', 'outcome_status', nullable=False, server_default='UNKNOWN')
    op.alter_column('operations', 'evidence_assurance', nullable=False, server_default='NONE')

    op.drop_constraint('ck_operations_state', 'operations', type_='check')
    op.drop_column('operations', 'state')

    op.create_check_constraint(
        'ck_operations_execution_stage', 'operations',
        "execution_stage IN ('AUTHORIZED','CLAIMED','DISPATCHED')",
    )
    op.create_check_constraint(
        'ck_operations_outcome_status', 'operations',
        "outcome_status IN ('UNKNOWN','COMMITTED','TERMINALLY_NOT_COMMITTED')",
    )
    op.create_check_constraint(
        'ck_operations_evidence_assurance', 'operations',
        "evidence_assurance IN ('NONE','REPORTED_UNVERIFIED','ADAPTER_REPORTED','MANUAL_ADJUDICATED')",
    )

    # --- 4. operation_evidence_events: evidence-acceptance-rule fields ---
    op.add_column('operation_evidence_events', sa.Column('reconciliation_outcome', sa.Text(), nullable=True))
    op.add_column('operation_evidence_events', sa.Column('rationale', sa.Text(), nullable=True))
    op.add_column('operation_evidence_events', sa.Column('evidence_reference_ids', sa.JSON(), nullable=True))

    op.drop_constraint('ck_operation_evidence_events_type', 'operation_evidence_events', type_='check')
    op.create_check_constraint(
        'ck_operation_evidence_events_type', 'operation_evidence_events',
        "event_type IN ('DISPATCH_REPORTED','OBSERVATION','OBSERVATION_CONFLICT_REJECTED','MANUAL_ADJUDICATION')",
    )
    op.drop_constraint('ck_operation_evidence_events_reporter_kind', 'operation_evidence_events', type_='check')
    op.create_check_constraint(
        'ck_operation_evidence_events_reporter_kind', 'operation_evidence_events',
        "reporter_kind IN ('SIGNED_ADAPTER_IDENTITY','RBAC_HUMAN','MANUAL_ADJUDICATION')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_operation_evidence_events_reporter_kind', 'operation_evidence_events', type_='check')
    op.create_check_constraint(
        'ck_operation_evidence_events_reporter_kind', 'operation_evidence_events',
        "reporter_kind IN ('SIGNED_ADAPTER_IDENTITY','RBAC_HUMAN')",
    )
    op.drop_constraint('ck_operation_evidence_events_type', 'operation_evidence_events', type_='check')
    op.create_check_constraint(
        'ck_operation_evidence_events_type', 'operation_evidence_events',
        "event_type IN ('DISPATCH_REPORTED','OBSERVATION')",
    )
    op.drop_column('operation_evidence_events', 'evidence_reference_ids')
    op.drop_column('operation_evidence_events', 'rationale')
    op.drop_column('operation_evidence_events', 'reconciliation_outcome')

    op.add_column('operations', sa.Column('state', sa.Text(), nullable=True))
    op.execute("""
        UPDATE operations SET state = CASE
            WHEN outcome_status = 'COMMITTED' THEN 'COMMITTED'
            WHEN outcome_status = 'TERMINALLY_NOT_COMMITTED' THEN 'TERMINALLY_NOT_COMMITTED'
            WHEN outcome_status = 'UNKNOWN' AND execution_stage IN ('CLAIMED', 'DISPATCHED') THEN 'OUTCOME_UNKNOWN'
            ELSE execution_stage
        END
    """)
    op.alter_column('operations', 'state', nullable=False, server_default='AUTHORIZED')
    op.create_check_constraint(
        'ck_operations_state', 'operations',
        "state IN ('AUTHORIZED','CLAIMED','DISPATCHED','COMMITTED','TERMINALLY_NOT_COMMITTED','OUTCOME_UNKNOWN')",
    )

    op.drop_constraint('ck_operations_evidence_assurance', 'operations', type_='check')
    op.drop_constraint('ck_operations_outcome_status', 'operations', type_='check')
    op.drop_constraint('ck_operations_execution_stage', 'operations', type_='check')
    op.drop_column('operations', 'evidence_assurance')
    op.drop_column('operations', 'outcome_status')
    op.drop_column('operations', 'execution_stage')

    op.drop_constraint('fk_boi_current_operation', 'business_operation_identities', type_='foreignkey')
    op.drop_index('idx_operations_business_identity', table_name='operations')
    op.drop_constraint('fk_operations_previous_attempt', 'operations', type_='foreignkey')
    op.drop_constraint('fk_operations_integration_contract_version', 'operations', type_='foreignkey')
    op.drop_constraint('fk_operations_integration', 'operations', type_='foreignkey')
    op.drop_constraint('fk_operations_business_operation_identity', 'operations', type_='foreignkey')
    op.drop_column('operations', 'previous_attempt_operation_id')
    op.drop_column('operations', 'integration_contract_version_id')
    op.drop_column('operations', 'integration_id')
    op.drop_column('operations', 'business_operation_identity_id')

    op.drop_index('idx_business_operation_identities_organization', table_name='business_operation_identities')
    op.drop_table('business_operation_identities')

    op.drop_column('intents', 'intended_destination')
    op.drop_column('intents', 'business_operation_id')
