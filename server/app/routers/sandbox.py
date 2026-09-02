"""Developer Distribution & Sandbox v1: the one new public surface this
milestone adds. Deliberately narrow -- it does exactly one thing (create
an isolated, capped, always-`environment="sandbox"` Organization with a
starter policy and a ready-to-use credential) and nothing else. It never
accepts, exposes, or requires the platform Operator Key; it is not a
general-purpose admin API, and it never lets a caller choose
`environment="production"`.

Everything this endpoint does internally is a real, unmodified call into
the exact same services every other org-creation/policy-authoring path
already uses (`organization_lifecycle_service.create_organization`,
`runtime_policy_service.create_policy`/`submit_for_review`/`approve`/
`compile_policy`/`deploy_policy`, `auth_service.generate_api_key`) --
this endpoint is a composition of existing, already-tested primitives,
not a new authority mechanism or a governance bypass. The starter policy
it provisions is approved by the new organization's own Owner (the
account this same request just created), the identical self-service path
any Owner already has for their own organization -- not a shortcut
around review that a normal user doesn't have.
"""

import logging
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ApiKey
from app.db.session import get_db
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.schemas.sandbox import CreateSandboxRequest, CreateSandboxResponse
from app.security import check_rate_limit, _client_key
from app.services import auth_service
from app.services import organization_lifecycle_service as org_svc
from app.services import runtime_policy_service as policy_svc

logger = logging.getLogger("payreality.sandbox")
router = APIRouter(prefix="/v1/sandbox", tags=["sandbox"])

# A dedicated, much stricter limit than the general per-IP request limit
# (_RATE_LIMIT_MAX_REQUESTS in security.py) -- creating an Organization
# is a fundamentally heavier, more abusable operation than an ordinary
# read/evaluate call, so it gets its own budget rather than sharing one.
# Never shared with _request_log: a burst of ordinary API traffic from
# one IP must not exhaust this endpoint's separate budget, or vice versa.
_SANDBOX_CREATE_WINDOW_SECONDS = 3600
_SANDBOX_CREATE_MAX_PER_IP = 3
_sandbox_create_log: dict[str, deque] = defaultdict(deque)

# The one starter policy every sandbox is provisioned with, matching
# INTEGRATION_KIT.md's own "low-risk reference action allowed" template
# verbatim -- purchase_order_create is a real, closed-vocabulary action
# (scope_vocabulary.KNOWN_SCOPES), so this compiles cleanly, unlike an
# invented action name would.
_STARTER_PRINCIPAL = "Sandbox Principal"
_STARTER_ACTION = "purchase_order_create"


def _opa_url() -> str:
    return settings.opa_url


@router.post("/organizations", response_model=CreateSandboxResponse, status_code=201)
def create_sandbox_organization(
    body: CreateSandboxRequest, request: Request, db: Session = Depends(get_db)
):
    client_key = _client_key(request)
    if not check_rate_limit(
        client_key, _sandbox_create_log, _SANDBOX_CREATE_WINDOW_SECONDS, _SANDBOX_CREATE_MAX_PER_IP
    ):
        raise HTTPException(status_code=429, detail="sandbox_creation_rate_limit_exceeded")

    if org_svc.find_sandbox_organization_by_owner_email(db, body.email) is not None:
        raise HTTPException(status_code=409, detail="sandbox_already_exists_for_email")

    organization, owner, temporary_password = org_svc.create_organization(
        db,
        name=body.name or f"Sandbox ({body.email})",
        owner_email=body.email,
        owner_name=body.name or body.email,
        environment="sandbox",
    )

    # The starter policy: created, submitted, approved, compiled, and
    # deployed through the real, unmodified lifecycle -- the same four
    # calls a human would make by hand in Policy Studio, just made once,
    # automatically, by this request, as the organization's own Owner.
    policy = RuntimePolicy(
        id=str(uuid.uuid4()),
        name="Sandbox starter: purchase order creation allowed",
        version=1,
        status=PolicyStatus.DRAFT,
        scope=Scope(principal=_STARTER_PRINCIPAL, action=_STARTER_ACTION),
        conditions=ConditionSet(all=()),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, organization.id)
    policy_svc.submit_for_review(db, row.policy_key, organization.id)
    policy_svc.approve(db, row.policy_key, organization.id, approver=f"sandbox-provisioning:{owner.email}")
    compiled = policy_svc.compile_policy(db, row.policy_key, organization.id)
    if not compiled.ok:
        logger.error(
            "sandbox_starter_policy_compile_failed organization_id=%s errors=%s",
            organization.id, compiled.diagnostics.errors,
        )
        raise HTTPException(status_code=500, detail="sandbox_starter_policy_compile_failed")
    policy_svc.deploy_policy(db, row.policy_key, organization.id, opa_url=_opa_url())

    # One ready-to-use API key, the exact same generate_api_key() +
    # ApiKey row shape routers/organization.py's own self-service
    # create_api_key endpoint already uses -- Owner role, since this is
    # the developer's own, single-occupant sandbox (matching how
    # create_organization's own temporary-password login is already
    # Owner-level for the same reason).
    raw_key, key_hash, key_prefix = auth_service.generate_api_key()
    api_key = ApiKey(
        organization_id=organization.id,
        name="Sandbox default key",
        key_hash=key_hash,
        key_prefix=key_prefix,
        role=owner.role,
    )
    db.add(api_key)
    db.commit()

    logger.info(
        "sandbox_organization_created organization_id=%s owner_email=%s",
        organization.id, owner.email,
    )
    return CreateSandboxResponse(
        organization_id=str(organization.id),
        organization_name=organization.name,
        api_key=raw_key,
        owner_email=owner.email,
        owner_temporary_password=temporary_password,
        starter_policy_key=str(row.policy_key),
    )
