from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DecisionResolution, EnterpriseSystem, IntegrationIdentity
from app.db.session import get_db
from app.dependencies import verify_integration_identity_signature
from app.domain.auth.signature import check_timestamp_window
from app.schemas.intent import DecisionSummary, SubmitIntentResponse
from app.schemas.integration_runtime import AttestedIntentRequest
from app.services import integration_runtime_service
from app.services.integration_runtime_service import (
    AdapterReplayDetectedError,
    ExternalOperationConflictError,
    IntegrationRejectionError,
)

router = APIRouter(prefix="/v1", tags=["integration-runtime"])


def _enterprise_system_name(db: Session, enterprise_system_id) -> str | None:
    if enterprise_system_id is None:
        return None
    system = db.get(EnterpriseSystem, enterprise_system_id)
    return system.name if system else None


@router.post("/integration-runtime/intents", response_model=SubmitIntentResponse)
def submit_attested_intent(
    body: AttestedIntentRequest,
    identity: IntegrationIdentity = Depends(verify_integration_identity_signature),
    db: Session = Depends(get_db),
):
    """Trusted Integration Architecture, Phase 2: the new, additive
    trusted-Adapter runtime path. Does not rename or replace
    POST /v1/intents (the Agent-direct path, unchanged, still lower-
    assurance) -- authentication is distinguished purely by which
    endpoint the request hits (this one requires an IntegrationIdentity
    certificate, never an Agent's), never inferred from any payload
    field.

    Trust claim, stated precisely: this endpoint verifies that an
    authenticated Integration Identity, acting under an active
    Enforcement Binding, attests to having observed this operation and
    constructed the canonical Intent using an approved Integration
    Contract. It does not prove the external operation actually
    executed, that the Adapter's own code is free of bugs, or that no
    other path to the same effect exists."""
    if body.integration_identity_id != identity.id:
        raise HTTPException(status_code=401, detail="integration_identity_id_does_not_match_signing_key")

    window_check = check_timestamp_window(body.requested_at, settings.intent_signature_window_seconds)
    if not window_check.ok:
        raise HTTPException(status_code=401, detail=window_check.reason)

    try:
        intent, decision, evidence = integration_runtime_service.submit_attested_intent(
            db,
            identity,
            enforcement_binding_id=body.enforcement_binding_id,
            origin_agent_id=body.origin_agent_id,
            source_operation=body.source_operation,
            action=body.action,
            resource=body.resource,
            amount=body.amount,
            currency=body.currency,
            counterparty=body.counterparty,
            context=body.context,
            requested_at=body.requested_at,
            nonce=body.nonce,
            correlation_id=body.correlation_id,
            external_operation_id=body.external_operation_id,
        )
    except IntegrationRejectionError as e:
        raise HTTPException(status_code=422, detail=f"integration_rejection:{e.reason}")
    except AdapterReplayDetectedError:
        raise HTTPException(status_code=409, detail="replay_detected")
    except ExternalOperationConflictError:
        # Section 27: do not disclose the mismatched canonical values in
        # the response body -- the typed detail code is enough for a
        # legitimate caller to understand what happened (their retry's
        # authority-relevant fields disagree with the original request
        # for this external_operation_id) without leaking amount/
        # resource/context specifics to whatever logged or observed
        # this response.
        raise HTTPException(status_code=409, detail="external_operation_conflict")

    # Trusted Integration Architecture, Phase 3: a matching retry can
    # return a HUMAN_REVIEW decision that has since actually been
    # resolved (section 12) -- the naive "HUMAN_REVIEW means PENDING"
    # rule that's correct for a brand-new submission (nothing could have
    # resolved it yet) is no longer sufficient once idempotent returns
    # of an *older* Decision are possible. Matches _build_decision_
    # response's own discipline in routers/intents.py.
    resolution_row = db.query(DecisionResolution).filter_by(decision_id=decision.id).one_or_none()
    status = "PENDING" if (decision.outcome == "HUMAN_REVIEW" and resolution_row is None) else "RESOLVED"

    return SubmitIntentResponse(
        intent_id=intent.id,
        decision=DecisionSummary(
            outcome=decision.outcome,
            decision_id=decision.id,
            evaluated_mandates=decision.evaluated_mandates or [],
            evaluated_mandate_ids=decision.evaluated_mandate_ids or [],
            enterprise_system_id=decision.enterprise_system_id,
            enterprise_system_name=_enterprise_system_name(db, decision.enterprise_system_id),
            reason=decision.reason,
        ),
        evidence_id=evidence.id,
        status=status,
        correlation_id=intent.correlation_id,
    )
