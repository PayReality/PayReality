from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EnterpriseFact, Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.fact import (
    FactResponse,
    FactSourceResponse,
    IngestFactRequest,
    RegisterFactSourceRequest,
)
from app.services import fact_service

router = APIRouter(prefix="/v1", tags=["facts"])


@router.post(
    "/fact-sources", response_model=FactSourceResponse,
    dependencies=[Depends(require_permission(Permission.FACTS_MANAGE))],
)
def register_fact_source(
    body: RegisterFactSourceRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Registering a source is a governance action (Permission.FACTS_MANAGE)
    -- deliberately distinct from ingesting a fact below, which is
    authenticated by the fact's own signature, not by RBAC."""
    source = fact_service.register_fact_source(db, organization.id, body.name, body.public_key_b64)
    return source


@router.post(
    "/fact-sources/{source_id}/revoke", response_model=FactSourceResponse,
    dependencies=[Depends(require_permission(Permission.FACTS_MANAGE))],
)
def revoke_fact_source(
    source_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        return fact_service.revoke_fact_source(db, organization.id, source_id)
    except fact_service.FactSourceNotFoundError:
        raise HTTPException(status_code=404, detail="fact_source_not_found")


@router.post("/facts", response_model=FactResponse)
def ingest_fact(body: IngestFactRequest, db: Session = Depends(get_db)):
    """Deliberately NOT gated by require_permission: the caller here is
    a registered enterprise system, not a human operator or an AI agent
    requesting authorization -- the same "the request authenticates
    itself" model POST /v1/intents already uses for Agents
    (verify_agent_signature), not an Operator Key or session. An AI
    agent's own signature can never substitute for a FactSource's: this
    endpoint only accepts a signature verified against a specific,
    already-registered FactSource.public_key, so an agent requesting
    authorization can never self-attest a consequential external fact
    (supplier_approved, budget_available, approval_granted,
    goods_received) about itself."""
    try:
        fact = fact_service.ingest_fact(
            db,
            organization_id=body.organization_id,
            source_id=body.source_id,
            subject=body.subject,
            key=body.key,
            value=body.value,
            observed_at=body.observed_at,
            expires_at=body.expires_at,
            nonce=body.nonce,
            signature_b64=body.signature,
        )
    except fact_service.FactSourceNotFoundError:
        raise HTTPException(status_code=404, detail="fact_source_not_found")
    except fact_service.FactSourceRevokedError:
        raise HTTPException(status_code=403, detail="fact_source_revoked")
    except fact_service.InvalidFactSignatureError:
        raise HTTPException(status_code=401, detail="invalid_fact_signature")
    except fact_service.FactReplayError:
        raise HTTPException(status_code=409, detail="fact_replay_detected")
    return fact


@router.get(
    "/facts", response_model=list[FactResponse],
    dependencies=[Depends(require_permission(Permission.FACTS_MANAGE))],
)
def list_facts(
    key: str | None = None,
    subject: str | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Debugging/visibility only -- not the path Runtime Authority itself
    reads (fact_service.resolve_facts, called from intent_service.py).
    Shows every currently-stored fact for this organization, expired or
    not, revoked-source or not, so a reviewer can see why a decision did
    or didn't see a given fact as trusted."""
    stmt = select(EnterpriseFact).where(EnterpriseFact.organization_id == organization.id)
    if key is not None:
        stmt = stmt.where(EnterpriseFact.key == key)
    if subject is not None:
        stmt = stmt.where(EnterpriseFact.subject == subject)
    stmt = stmt.order_by(EnterpriseFact.recorded_at.desc())
    return list(db.scalars(stmt))
