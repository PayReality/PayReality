"""Product Experience V3.2, Part C ("Draft with AI"). Every endpoint here
is gated on the SAME permission the manual builder's own save endpoint
already requires (Permission.RUNTIME_POLICY_EDIT) -- section 43's own
non-negotiable: a user who cannot edit rules must not gain editing
ability through the AI assistant. Nothing here saves, publishes,
approves, or activates anything; every response is a proposal for the
caller to apply manually through the existing save/lifecycle endpoints
(section 42's hard safety boundaries)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.policy_drafting import DraftRequest, DraftResponse, ExplainRequest, ExplainResponse, UnknownEntityResponse
from app.services import policy_drafting_service as svc

router = APIRouter(prefix="/v1/policy-drafting", tags=["policy-drafting"])


@router.post(
    "/draft", response_model=DraftResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def draft_or_edit(
    body: DraftRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        result = svc.draft_or_edit(db, organization, body.instruction, body.current_draft)
    except svc.AIDraftingNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return DraftResponse(
        proposal=result.content,
        clarifying_question=result.clarifying_question,
        unknown_entities=[UnknownEntityResponse(field=u.field, value=u.value) for u in result.unknown_entities],
        requires_additional_policies=result.requires_additional_policies,
        additional_policies_note=result.additional_policies_note,
        confidence=result.confidence,
        missing_fields=list(result.missing_fields),
    )


@router.post(
    "/explain", response_model=ExplainResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def explain(
    body: ExplainRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        explanation = svc.explain(db, organization, body.current_draft, body.deterministic_summary, body.question)
    except svc.AIDraftingNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return ExplainResponse(explanation=explanation)
