"""Trusted Integration Architecture, Phase 1: the Integration Contract
kernel's lifecycle, validation, content-hash, RBAC-boundary, and org-
isolation behavior -- and, just as importantly, proof that none of it
has any effect on existing runtime behavior. Follows this codebase's
established real-SQLite integration test convention (no OPA, no
concurrency needed here -- see test_integration_contract_concurrency.py
for the real-Postgres concurrency proof).
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Agent, Base, Decision, Evidence, Intent, Organization, Principal,
    Integration, IntegrationContractVersion,
)
from app.services import integration_contract_service as svc
from app.services.integration_contract_service import (
    ConcurrentVersionConflictError,
    ContractInvalidTransitionError,
    ContractValidationError,
    ContractVersionNotFoundError,
    IntegrationNotFoundError,
)


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(engine)
    finally:
        policies_table.indexes.add(partial_index)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    return org


@pytest.fixture()
def other_org(db):
    org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(org)
    db.commit()
    return org


def _create(db, org_id, source_operation="ChangeSupplierBankDetails", canonical_action="vendor_payment", **kw):
    integration = svc.create_integration(db, org_id, "SAP S/4HANA (reference)", created_by="dev@example.com")
    version = svc.create_contract_version(
        db, integration.id, org_id, source_operation, canonical_action, **kw,
    )
    return integration, version


# --- Integration ---------------------------------------------------------


def test_create_integration_is_minimal_and_org_scoped(db, org):
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)", created_by="dev@example.com")
    assert integration.organization_id == org.id
    assert integration.external_system_label == "SAP S/4HANA (reference)"
    # No status field, no connector credentials, no runtime identity --
    # confirmed by construction: the model itself carries none of these.
    assert not hasattr(integration, "status")


def test_integration_organization_isolation_is_not_found_not_forbidden(db, org, other_org):
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    with pytest.raises(IntegrationNotFoundError):
        svc.get_integration(db, integration.id, other_org.id)


def test_list_integrations_never_crosses_organizations(db, org, other_org):
    svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    svc.create_integration(db, other_org.id, "Workday (reference)")
    assert len(svc.list_integrations(db, org.id)) == 1
    assert len(svc.list_integrations(db, other_org.id)) == 1


# --- DRAFT creation / editing ---------------------------------------------


def test_create_draft_contract_version_starts_at_version_one(db, org):
    _integration, version = _create(db, org.id, resource_path="supplier.id")
    assert version.status == "draft"
    assert version.version == 1
    assert version.content_hash is None  # not computed until validated


def test_edit_draft_updates_only_supplied_fields(db, org):
    _integration, version = _create(db, org.id, resource_path="supplier.id")
    edited = svc.edit_draft_contract_version(
        db, version.id, org.id, fact_subject_path="supplier.id",
    )
    assert edited.resource_path == "supplier.id"  # untouched
    assert edited.fact_subject_path == "supplier.id"  # newly set


def test_edit_draft_can_explicitly_clear_an_optional_path(db, org):
    _integration, version = _create(db, org.id, resource_path="supplier.id")
    edited = svc.edit_draft_contract_version(db, version.id, org.id, resource_path=None)
    assert edited.resource_path is None


def test_cannot_edit_a_validated_version(db, org):
    _integration, version = _create(db, org.id)
    validated = svc.validate_contract_version(db, version.id, org.id)
    with pytest.raises(ContractInvalidTransitionError):
        svc.edit_draft_contract_version(db, validated.id, org.id, resource_path="new.path")


# --- Validation ------------------------------------------------------------


def test_validation_success_computes_content_hash_and_advances_status(db, org):
    _integration, version = _create(db, org.id, resource_path="supplier.id")
    validated = svc.validate_contract_version(db, version.id, org.id)
    assert validated.status == "validated"
    assert validated.content_hash is not None
    assert validated.validated_at is not None


def test_unrecognized_canonical_action_is_rejected(db, org):
    with pytest.raises(ContractValidationError):
        _create(db, org.id, canonical_action="not_a_real_action")


def test_malformed_resource_path_is_rejected(db, org):
    with pytest.raises(ContractValidationError):
        _create(db, org.id, resource_path="supplier..id")


def test_malformed_context_binding_path_is_rejected(db, org):
    with pytest.raises(ContractValidationError):
        _create(db, org.id, context_bindings={"department": "..bad"})


def test_invalid_context_binding_key_is_rejected(db, org):
    with pytest.raises(ContractValidationError):
        _create(db, org.id, context_bindings={"not a valid key": "supplier.department"})


def test_validation_does_not_require_a_runtime_policy_or_live_system(db, org):
    """Section 11: the Contract represents approved semantic meaning
    independently of whichever RuntimePolicies happen to exist today --
    no RuntimePolicy row exists anywhere in this test's fixtures at all."""
    _integration, version = _create(db, org.id, resource_path="supplier.id")
    validated = svc.validate_contract_version(db, version.id, org.id)
    assert validated.status == "validated"


# --- Content hash determinism ----------------------------------------------


def test_content_hash_is_deterministic(db, org):
    """Two different Integrations, each mapping the SAME source_operation
    with byte-equivalent semantic fields, both land at version=1 (version
    is scoped per (integration_id, source_operation), so two different
    integration_ids never share a version sequence) -- and must hash
    identically, since source_operation is unchanged and every other
    hashed field matches."""
    _integration, v1 = _create(db, org.id, resource_path="supplier.id")
    validated1 = svc.validate_contract_version(db, v1.id, org.id)
    integration2 = svc.create_integration(db, org.id, "SAP S/4HANA (second reference)")
    v2 = svc.create_contract_version(
        db, integration2.id, org.id, "ChangeSupplierBankDetails", "vendor_payment", resource_path="supplier.id",
    )
    validated2 = svc.validate_contract_version(db, v2.id, org.id)
    assert validated1.content_hash == validated2.content_hash, (
        "byte-equivalent semantic content across two different rows must hash identically"
    )


def test_context_bindings_key_order_never_changes_the_hash(db, org):
    integration1 = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    integration2 = svc.create_integration(db, org.id, "SAP S/4HANA (second reference)")
    v1 = svc.create_contract_version(
        db, integration1.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
        context_bindings={"department": "dept.name", "region": "region.code"},
    )
    v2 = svc.create_contract_version(
        db, integration2.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
        context_bindings={"region": "region.code", "department": "dept.name"},
    )
    h1 = svc.validate_contract_version(db, v1.id, org.id).content_hash
    h2 = svc.validate_contract_version(db, v2.id, org.id).content_hash
    assert h1 == h2


def test_source_schema_fingerprint_is_excluded_from_the_hash(db, org):
    """Founder decision (&sect;9/&sect;10 of the addendum, and this
    milestone's own &sect;10): source_schema_fingerprint is provenance,
    not semantic content."""
    integration1 = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    integration2 = svc.create_integration(db, org.id, "SAP S/4HANA (second reference)")
    v1 = svc.create_contract_version(
        db, integration1.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
        source_schema_fingerprint="fingerprint-a",
    )
    v2 = svc.create_contract_version(
        db, integration2.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
        source_schema_fingerprint="fingerprint-b",
    )
    h1 = svc.validate_contract_version(db, v1.id, org.id).content_hash
    h2 = svc.validate_contract_version(db, v2.id, org.id).content_hash
    assert h1 == h2, "two different fingerprints with identical semantic fields must still hash identically"


def test_version_number_is_excluded_from_the_hash(db, org):
    """The most direct proof: version 1 and version 2 of the SAME
    (integration_id, source_operation), with identical semantic fields
    re-supplied on purpose, must hash identically despite differing in
    `version` -- the one field the hash is defined to ignore."""
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    v1 = svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment", resource_path="a.b",
    )
    h1 = svc.validate_contract_version(db, v1.id, org.id).content_hash
    v2 = svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment", resource_path="a.b",
    )
    assert v2.version == 2
    h2 = svc.validate_contract_version(db, v2.id, org.id).content_hash
    assert h1 == h2


# --- Approval / RBAC boundary (service-level; router RBAC is exercised in
#     test_rbac_permissions.py at the permission-definition level) --------


def test_approve_requires_validated_status(db, org):
    _integration, version = _create(db, org.id)
    with pytest.raises(ContractInvalidTransitionError):
        svc.approve_contract_version(db, version.id, org.id, approver="governance-admin@example.com")


def test_approve_records_approver_and_timestamp(db, org):
    _integration, version = _create(db, org.id)
    validated = svc.validate_contract_version(db, version.id, org.id)
    approved = svc.approve_contract_version(db, validated.id, org.id, approver="governance-admin@example.com")
    assert approved.status == "approved"
    assert approved.approved_by == "governance-admin@example.com"
    assert approved.approved_at is not None


# --- Lifecycle correction: multiple APPROVED versions may coexist ---------


def test_approving_a_new_version_never_retires_the_previous_approved_version(db, org):
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    v1 = svc.create_contract_version(db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment")
    v1 = svc.validate_contract_version(db, v1.id, org.id)
    v1 = svc.approve_contract_version(db, v1.id, org.id, approver="governance-admin@example.com")

    v2 = svc.create_contract_version(db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment")
    v2 = svc.validate_contract_version(db, v2.id, org.id)
    v2 = svc.approve_contract_version(db, v2.id, org.id, approver="governance-admin@example.com")

    # Re-read both rows fresh -- v1 must still be approved, not silently
    # retired as a side effect of v2's own approval.
    v1_reloaded = svc.get_contract_version(db, v1.id, org.id)
    v2_reloaded = svc.get_contract_version(db, v2.id, org.id)
    assert v1_reloaded.status == "approved"
    assert v2_reloaded.status == "approved"
    assert v1_reloaded.version == 1
    assert v2_reloaded.version == 2


def test_no_db_constraint_prevents_multiple_approved_versions_for_one_operation(db, org):
    """Explicit negative-space test for the lifecycle correction: there
    is no partial-unique-on-approved index (unlike Policy/Certificate),
    by design -- multiple APPROVED versions of the same
    (integration_id, source_operation) legitimately coexist until
    Phase 2's EnforcementBinding selects one."""
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    for _ in range(3):
        v = svc.create_contract_version(db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment")
        v = svc.validate_contract_version(db, v.id, org.id)
        svc.approve_contract_version(db, v.id, org.id, approver="governance-admin@example.com")
    versions = svc.list_contract_versions(db, integration.id, org.id)
    assert [v.status for v in versions] == ["approved", "approved", "approved"]


# --- Retirement --------------------------------------------------------------


def test_retirement_requires_approved_status(db, org):
    _integration, version = _create(db, org.id)
    with pytest.raises(ContractInvalidTransitionError):
        svc.retire_contract_version(db, version.id, org.id)


def test_explicit_retirement(db, org):
    _integration, version = _create(db, org.id)
    validated = svc.validate_contract_version(db, version.id, org.id)
    approved = svc.approve_contract_version(db, validated.id, org.id, approver="governance-admin@example.com")
    retired = svc.retire_contract_version(db, approved.id, org.id)
    assert retired.status == "retired"
    assert retired.retired_at is not None


def test_retired_record_remains_queryable_historically(db, org):
    _integration, version = _create(db, org.id)
    validated = svc.validate_contract_version(db, version.id, org.id)
    approved = svc.approve_contract_version(db, validated.id, org.id, approver="governance-admin@example.com")
    retired = svc.retire_contract_version(db, approved.id, org.id)
    fetched = svc.get_contract_version(db, retired.id, org.id)
    assert fetched.status == "retired"
    assert fetched.content_hash == retired.content_hash  # unchanged, immutable historical record


def test_retirement_never_hard_deletes(db, org):
    _integration, version = _create(db, org.id)
    validated = svc.validate_contract_version(db, version.id, org.id)
    approved = svc.approve_contract_version(db, validated.id, org.id, approver="governance-admin@example.com")
    svc.retire_contract_version(db, approved.id, org.id)
    still_there = db.scalar(select(IntegrationContractVersion).where(IntegrationContractVersion.id == approved.id))
    assert still_there is not None


# --- Cross-org access hidden -------------------------------------------------


def test_contract_version_cross_org_access_is_not_found(db, org, other_org):
    _integration, version = _create(db, org.id)
    with pytest.raises(ContractVersionNotFoundError):
        svc.get_contract_version(db, version.id, other_org.id)


def test_list_contract_versions_requires_owning_organization(db, org, other_org):
    integration, _version = _create(db, org.id)
    with pytest.raises(IntegrationNotFoundError):
        svc.list_contract_versions(db, integration.id, other_org.id)


# --- No runtime side effects -------------------------------------------------


def test_creating_and_approving_contracts_has_zero_runtime_side_effects(db, org):
    """Backwards-compatibility proof: nothing in this milestone writes
    an Intent, Decision, or Evidence row, ever."""
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    for i in range(3):
        v = svc.create_contract_version(db, integration.id, org.id, f"Op{i}", "vendor_payment")
        v = svc.validate_contract_version(db, v.id, org.id)
        svc.approve_contract_version(db, v.id, org.id, approver="governance-admin@example.com")

    assert db.scalars(select(Intent)).all() == []
    assert db.scalars(select(Decision)).all() == []
    assert db.scalars(select(Evidence)).all() == []


def test_business_operation_identity_columns_now_exist(db, org):
    """Migration/backwards-compat proof at the schema level: Intent now
    legitimately carries integration_contract_version_id/
    integration_identity_id/enforcement_binding_id/environment (Trusted
    Integration Architecture, Phase 2) and external_operation_id/
    integration_id/canonical_operation_fingerprint (Phase 3, business-
    operation idempotency, operation_identity_service.py) -- all
    nullable and additive, none of it required for the Agent-direct
    path this file's own zero-runtime-side-effects test above already
    covers."""
    intent_columns = {c.name for c in Intent.__table__.columns}
    assert "integration_contract_version_id" in intent_columns
    assert "external_operation_id" in intent_columns
    assert "integration_id" in intent_columns
    assert "canonical_operation_fingerprint" in intent_columns
