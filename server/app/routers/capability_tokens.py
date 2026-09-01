import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.capability import token as capability_token
from app.domain.rbac.permissions import Permission
from app.schemas.capability import (
    IssueCapabilityRequest,
    IssueCapabilityResponse,
    VerifyCapabilityRequest,
    VerifyCapabilityResponse,
)
from app.services import capability_service, intent_service

router = APIRouter(prefix="/v1", tags=["capabilities"])
logger = logging.getLogger("payreality.capability")


@router.post(
    "/decisions/{decision_id}/capability-token", response_model=IssueCapabilityResponse,
    dependencies=[Depends(require_permission(Permission.CAPABILITY_ISSUE))],
)
def issue_capability(
    decision_id: UUID,
    body: IssueCapabilityRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Gated on Permission.CAPABILITY_ISSUE, deliberately NOT
    Permission.DECISIONS_VIEW -- viewing a decision and minting an
    executable authorization capability for it are different
    privileges (PAYREALITY_FUTURE_VISION.md Part C's own C6)."""
    try:
        issued = capability_service.issue_capability_for_decision(
            db, organization.id, decision_id, audience=body.audience,
            issued_by=body.issued_by,
            ttl_seconds=body.ttl_seconds or capability_service.DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS,
        )
    except intent_service.DecisionNotFoundError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except intent_service.CrossOrganizationAccessError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except capability_service.DecisionNotAllowError:
        raise HTTPException(status_code=409, detail="decision_not_allow")
    except capability_service.IntegrationIdentityNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"integration_identity_not_active: {e}")
    except capability_service.EnforcementBindingNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"enforcement_binding_not_active: {e}")
    except capability_service.OriginAgentNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"origin_agent_not_active: {e}")
    except capability_service.CapabilityAlreadyIssuedError as e:
        raise HTTPException(status_code=409, detail=f"capability_already_issued: {e}")
    except capability_service.CapabilityAlreadyConsumedForDecisionError as e:
        raise HTTPException(status_code=409, detail=f"capability_already_consumed_for_decision: {e}")
    except capability_service.CapabilityExpiredNotRenewedError as e:
        raise HTTPException(status_code=409, detail=f"capability_expired_not_renewed: {e}")
    return IssueCapabilityResponse(
        token=issued.token, capability_id=issued.capability_id, expires_at=issued.expires_at
    )


@router.post(
    "/decisions/{decision_id}/capability-token/from-review", response_model=IssueCapabilityResponse,
    dependencies=[Depends(require_permission(Permission.CAPABILITY_ISSUE))],
)
def issue_capability_from_review(
    decision_id: UUID,
    body: IssueCapabilityRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Trusted Integration Architecture, Phase 5.1, Part B: issues a
    Capability for a HUMAN_REVIEW decision an authorized reviewer has
    since approved, without ever mutating the original Decision (it
    still reads outcome=='HUMAN_REVIEW' -- see capability_service.
    issue_capability_for_reviewed_decision's own docstring). Deliberately
    a separate endpoint from the one above, not a branch inside it: the
    two have genuinely different preconditions (ALLOW vs. an approved
    review resolution), and keeping them visibly distinct in the API
    surface matches keeping them visibly distinct in the service layer
    (section 11's own instruction not to conflate a resolution with an
    unrelated new ALLOW decision).

    Gated on the same Permission.CAPABILITY_ISSUE as direct issuance,
    deliberately not a new permission -- minting a capability is the
    same privilege either way; who was allowed to APPROVE the review was
    already checked when the resolution itself was created (Permission.
    DECISIONS_RESOLVE, see resolution_service.resolve_decision)."""
    try:
        issued = capability_service.issue_capability_for_reviewed_decision(
            db, organization.id, decision_id, audience=body.audience,
            issued_by=body.issued_by,
            ttl_seconds=body.ttl_seconds or capability_service.DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS,
        )
    except intent_service.DecisionNotFoundError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except intent_service.CrossOrganizationAccessError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except capability_service.DecisionNotHumanReviewError as e:
        raise HTTPException(status_code=409, detail=f"decision_not_human_review: {e}")
    except capability_service.ReviewNotResolvedError:
        raise HTTPException(status_code=409, detail="review_not_resolved")
    except capability_service.ReviewNotApprovedError as e:
        raise HTTPException(status_code=409, detail=f"review_not_approved: {e}")
    except capability_service.IntegrationIdentityNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"integration_identity_not_active: {e}")
    except capability_service.EnforcementBindingNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"enforcement_binding_not_active: {e}")
    except capability_service.OriginAgentNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"origin_agent_not_active: {e}")
    except capability_service.CapabilityAlreadyIssuedError as e:
        raise HTTPException(status_code=409, detail=f"capability_already_issued: {e}")
    except capability_service.CapabilityAlreadyConsumedForDecisionError as e:
        raise HTTPException(status_code=409, detail=f"capability_already_consumed_for_decision: {e}")
    except capability_service.CapabilityExpiredNotRenewedError as e:
        raise HTTPException(status_code=409, detail=f"capability_expired_not_renewed: {e}")
    return IssueCapabilityResponse(
        token=issued.token, capability_id=issued.capability_id, expires_at=issued.expires_at
    )


@router.post(
    "/capability-tokens/verify", response_model=VerifyCapabilityResponse,
    dependencies=[Depends(require_permission(Permission.CAPABILITY_VERIFY))],
)
def verify_capability(
    body: VerifyCapabilityRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Phase 6.1, Part B (Tenant Scoped Verification Identity): Phase 6's
    own hostile review reconfirmed this endpoint had no per-request
    tenant scope at all -- gated only on the platform-wide Operator Key,
    with no way to express "this caller may only verify THIS
    organisation's Capabilities." That was not itself a cross-tenant
    bypass (token lookup is by the token's own unique hash, so no
    caller's request can ever be confused for another's), but it was a
    real, avoidable trust-boundary gap this section closes.

    Now gated exactly like every other org-scoped Capability endpoint
    (require_permission + get_current_organization) rather than the bare
    Operator-Key-only check this used before -- reusing the existing
    RBAC/ApiKey machinery, not a new identity concept: an organisation
    creates a real, tenant-bound `ApiKey` with a role holding
    Permission.CAPABILITY_VERIFY (the same way Governance Administrator
    already holds CAPABILITY_ISSUE) and hands it to its own reference
    PEP. The platform Operator Key still works here too (Milestone 2's
    own model: it must now name its target organisation explicitly via
    X-PayReality-Organization-Id) -- preserved deliberately, not
    silently broken, and still narrowed by the same tenant check below,
    not exempt from it.

    `organization.id` is always passed through as
    `expected_organization_id`, so a Capability signed for a different
    organisation is rejected (CapabilityTenantMismatchError) regardless
    of which of the two auth paths the caller used."""
    try:
        consumed = capability_service.verify_and_consume_capability(
            db, body.token, body.audience, body.action, body.resource, body.constraints,
            environment=body.environment, enforcement_binding_id=body.enforcement_binding_id,
            principal=body.principal, expected_organization_id=organization.id,
        )
    except capability_service.CapabilityTokenNotFoundError:
        logger.warning("capability_verification_result=NOT_FOUND")
        raise HTTPException(status_code=404, detail="capability_token_not_found")
    except capability_token.CapabilityTokenExpiredError:
        logger.warning("capability_verification_result=EXPIRED")
        raise HTTPException(status_code=401, detail="capability_token_expired")
    except capability_token.CapabilityTenantMismatchError:
        logger.warning("capability_verification_result=TENANT_MISMATCH organization_id=%s", organization.id)
        raise HTTPException(status_code=403, detail="capability_tenant_mismatch")
    except capability_token.CapabilityAudienceMismatchError:
        logger.warning("capability_verification_result=AUDIENCE_MISMATCH audience=%s", body.audience)
        raise HTTPException(status_code=403, detail="capability_audience_mismatch")
    except capability_token.CapabilityConstraintMismatchError:
        logger.warning("capability_verification_result=CONSTRAINT_MISMATCH audience=%s", body.audience)
        raise HTTPException(status_code=409, detail="capability_constraint_mismatch")
    except capability_token.CapabilityBindingMismatchError:
        logger.warning("capability_verification_result=BINDING_MISMATCH audience=%s", body.audience)
        raise HTTPException(status_code=409, detail="capability_binding_mismatch")
    except capability_token.InvalidCapabilityTokenError:
        logger.warning("capability_verification_result=INVALID_SIGNATURE_OR_MALFORMED")
        raise HTTPException(status_code=401, detail="invalid_capability_token")
    except capability_service.CapabilityTokenAlreadyConsumedError:
        raise HTTPException(status_code=409, detail="capability_token_already_consumed")
    except capability_service.OriginAgentNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"origin_agent_not_active: {e}")
    except capability_service.IntegrationIdentityNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"integration_identity_not_active: {e}")
    except capability_service.EnforcementBindingNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"enforcement_binding_not_active: {e}")
    except capability_service.TenantNotActiveError as e:
        raise HTTPException(status_code=409, detail=f"tenant_not_active: {e}")
    return VerifyCapabilityResponse(
        capability_id=consumed.capability_id, decision_id=consumed.decision_id,
        resource=consumed.resource, constraints=consumed.constraints,
    )
