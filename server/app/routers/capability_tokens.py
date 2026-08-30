from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.capability import token as capability_token
from app.domain.rbac.permissions import Permission
from app.security import verify_operator_key
from app.schemas.capability import (
    IssueCapabilityRequest,
    IssueCapabilityResponse,
    VerifyCapabilityRequest,
    VerifyCapabilityResponse,
)
from app.services import capability_service, intent_service

router = APIRouter(prefix="/v1", tags=["capabilities"])


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
    except capability_service.CapabilityNotAvailableForIntegrationIntentError as e:
        raise HTTPException(status_code=409, detail=f"capability_not_available_for_integration_intent: {e}")
    return IssueCapabilityResponse(
        token=issued.token, capability_id=issued.capability_id, expires_at=issued.expires_at
    )


@router.post(
    "/capability-tokens/verify", response_model=VerifyCapabilityResponse,
    dependencies=[Depends(verify_operator_key)],
)
def verify_capability(body: VerifyCapabilityRequest, db: Session = Depends(get_db)):
    """The reference enforcement adapter's own call (scripts/
    reference_enforcement_adapter.py) -- gated on the Operator-Key-only
    check, the same platform-admin-machine-caller primitive
    process_due_schedules already uses, since a reference PEP is a
    trusted internal/platform-level caller with no human RBAC session of
    its own, not a human operator and not a signature-bearing identity
    like an Agent or a FactSource."""
    try:
        consumed = capability_service.verify_and_consume_capability(
            db, body.token, body.audience, body.action, body.resource, body.constraints
        )
    except capability_service.CapabilityTokenNotFoundError:
        raise HTTPException(status_code=404, detail="capability_token_not_found")
    except capability_token.CapabilityTokenExpiredError:
        raise HTTPException(status_code=401, detail="capability_token_expired")
    except capability_token.CapabilityAudienceMismatchError:
        raise HTTPException(status_code=403, detail="capability_audience_mismatch")
    except capability_token.CapabilityConstraintMismatchError:
        raise HTTPException(status_code=409, detail="capability_constraint_mismatch")
    except capability_token.InvalidCapabilityTokenError:
        raise HTTPException(status_code=401, detail="invalid_capability_token")
    except capability_service.CapabilityTokenAlreadyConsumedError:
        raise HTTPException(status_code=409, detail="capability_token_already_consumed")
    return VerifyCapabilityResponse(
        capability_id=consumed.capability_id, decision_id=consumed.decision_id,
        resource=consumed.resource, constraints=consumed.constraints,
    )
