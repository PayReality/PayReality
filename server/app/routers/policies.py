from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.policy import (
    ActivatePolicyResponse,
    AuthorityResponse,
    CompilePolicyResponse,
    DocumentResponse,
    PolicyResponse,
    ReviewAuthorityRequest,
)
from app.services import document_service, policy_service, review_service

router = APIRouter(prefix="/v1/policies", tags=["policies"])


@router.get(
    "/documents", response_model=list[DocumentResponse],
    dependencies=[Depends(require_permission(Permission.AUDIT_EXPORT))],
)
def list_documents(db: Session = Depends(get_db)):
    """Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md): this
    endpoint previously had no authentication at all -- a CRITICAL
    finding from Milestone 11's sweep. Gated with Permission.AUDIT_EXPORT
    (Owner-only) rather than a per-org view permission because `documents`
    has no organization_id column at all (it predates multi-tenancy, and
    the retired legacy pipeline it fed -- see _RETIRED_DETAIL below --
    confirmed zero rows exist in production as of 2026-07-29): there is
    no ownership chain this table can be scoped by without a schema
    change, which is out of this milestone's scope. Deliberately does
    NOT also depend on get_current_organization: there is nothing to
    scope by, and adding an unused organization parameter would
    misleadingly imply isolation this table structurally cannot provide
    yet. Requiring authentication plus the most restrictive existing
    permission is the honest, smallest fix available -- documented as a
    residual, disclosed limitation
    (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md), not silently
    presented as fully org-isolated when it isn't."""
    return [DocumentResponse.from_model(d) for d in document_service.list_documents(db)]


_RETIRED_DETAIL = (
    "retired: this legacy Authority/Mandate authoring path is disabled "
    "(PHASE_0.md) -- author and deploy Runtime Policies via /v1/runtime-policies "
    "instead. Read-only endpoints on this router (list documents/authorities/policies) "
    "remain available for historical/audit access."
)


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_CREATE))],
)
async def upload_document(file: UploadFile, db: Session = Depends(get_db)):
    """Retired (PHASE_0.md): this endpoint fed the legacy Authority/Mandate
    pipeline, which independently wrote to the same OPA package and the
    same active-Policy-row slot as runtime_policy_service.deploy_policy
    with zero coordination between the two. Confirmed via production data
    (2026-07-29) that zero legacy documents/authorities exist, so no
    backfill was required -- this simply closes the write path rather
    than migrating live data. Kept as a 410, not removed outright, so an
    unexpected caller is observable rather than silently 404ing."""
    raise HTTPException(status_code=410, detail=_RETIRED_DETAIL)


@router.get(
    "/authorities", response_model=list[AuthorityResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def list_authorities(
    document_id: UUID | None = None,
    status: str | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """spec 19.2.

    Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md): this
    endpoint previously had no authentication or organisation scoping at
    all -- a CRITICAL finding from Milestone 11's sweep. Gated with
    Permission.AUTHORITY_REVIEW, the same (only) permission this
    codebase defines for authority visibility/action -- there is no
    separate, weaker view-only permission for authorities the way
    Runtime Policy has RUNTIME_POLICY_VIEW distinct from CREATE/EDIT/
    PUBLISH, so the existing write-gating permission is reused for reads
    too, per "use the existing permission model, don't invent one."
    Organisation-scoped via Authority.principal_id -> Principal.
    organization_id (review_service.list_authorities_for_review), the
    only ownership chain this table has, since Authority predates
    multi-tenancy and carries no organization_id column of its own."""
    items = review_service.list_authorities_for_review(
        db, organization.id, document_id=document_id, status=status
    )
    return [AuthorityResponse.from_model(i.authority, i.validation_flags) for i in items]


@router.patch(
    "/authorities/{authority_id}",
    response_model=AuthorityResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def review_authority(
    authority_id: UUID, body: ReviewAuthorityRequest, db: Session = Depends(get_db)
):
    """Retired (PHASE_0.md) -- see upload_document's docstring."""
    raise HTTPException(status_code=410, detail=_RETIRED_DETAIL)


@router.post(
    "/{document_id}/compile",
    response_model=CompilePolicyResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def compile_policy(document_id: UUID, db: Session = Depends(get_db)):
    """Retired (PHASE_0.md) -- see upload_document's docstring."""
    raise HTTPException(status_code=410, detail=_RETIRED_DETAIL)


@router.post(
    "/{policy_id}/activate",
    response_model=ActivatePolicyResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def activate_policy(policy_id: UUID, db: Session = Depends(get_db)):
    """Retired (PHASE_0.md): this was the legacy pipeline's OPA-writing
    endpoint -- the actual source of the two-uncoordinated-writers risk
    PHASE_0.md identifies. See upload_document's docstring."""
    raise HTTPException(status_code=410, detail=_RETIRED_DETAIL)


@router.get(
    "", response_model=list[PolicyResponse],
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def list_policies(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md): this
    endpoint previously had no authentication or organisation scoping at
    all -- the CRITICAL finding Milestone 11's sweep discovered and this
    milestone closes, confirmed live-exploitable in production before
    this fix. Gated with Permission.RUNTIME_POLICY_VIEW, the same
    permission GET /v1/decisions/{id}/explanation and .../policy-binding
    already use to read this exact same `Policy` model -- reusing the
    established permission for this resource, not inventing a new one.
    Organisation-scoped via Policy.organization_id directly (the same
    column Historical Policy Binding and every other Policy-reading
    code path in this codebase already scopes by)."""
    return [PolicyResponse.from_model(p) for p in policy_service.list_policies(db, organization.id)]
