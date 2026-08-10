import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user_if_session, require_permission
from app.domain.compiler_v2.compiler_v2 import FINANCIAL_VOCABULARY
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail, Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.domain.rbac.permissions import Permission
from app.schemas.runtime_policy import (
    ApproveRequest,
    CompileResponse,
    CompilerErrorSchema,
    ConditionSchema,
    ConstraintsSchema,
    DeployResponse,
    DiffResponse,
    DryRunRequest,
    DryRunResponse,
    MetadataSchema,
    RejectRequest,
    RuntimePolicyRequest,
    RuntimePolicyResponse,
    ScopeSchema,
)
from app.services import runtime_policy_service as svc
from app.services.runtime_policy_service import (
    BundleChangedSinceCompileError,
    CompilationRequiredError,
    InvalidTransitionError,
    RuntimePolicyNotFoundError,
    UnexpectedActiveWriterError,
)

router = APIRouter(prefix="/v1/runtime-policies", tags=["runtime-policies"])


def _opa_url() -> str:
    return settings.opa_url


def _build_runtime_policy(
    req: RuntimePolicyRequest, policy_id: str, version: int, status: PolicyStatus, audit: AuditTrail,
    preserve_authority_id: str | None = None, preserve_mandate_id: str | None = None,
) -> RuntimePolicy:
    """Authority-as-a-continuous-object, Stage G: `preserve_authority_id`/
    `preserve_mandate_id` exist because today's Policy Studio UI has no
    field for either (Stage I is what adds one) -- if edit_policy simply
    trusted whatever the client's RuntimePolicyRequest sent for these,
    every edit through the existing, unmodified frontend would silently
    erase them. When set, these always win over whatever `req` carries."""
    try:
        conditions = tuple(
            Condition(field=c.field, operator=Operator(c.operator), value=c.value)
            for c in req.conditions
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"unsupported_operator: {e}")

    try:
        effect = Effect(req.effect)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid_effect: '{req.effect}'")

    risk_level = RiskLevel(req.constraints.risk_level) if req.constraints.risk_level else None

    return RuntimePolicy(
        id=policy_id,
        name=req.name,
        description=req.description,
        version=version,
        status=status,
        scope=Scope(
            principal=req.scope.principal,
            action=req.scope.action,
            agent=req.scope.agent,
            resource=req.scope.resource,
        ),
        conditions=ConditionSet(all=conditions),
        effect=effect,
        constraints=Constraints(
            delegated_by=req.constraints.delegated_by,
            expires=req.constraints.expires,
            evidence_required=req.constraints.evidence_required,
            risk_level=risk_level,
            authority_id=(
                preserve_authority_id if preserve_authority_id is not None else req.constraints.authority_id
            ),
            mandate_id=(
                preserve_mandate_id if preserve_mandate_id is not None else req.constraints.mandate_id
            ),
            # Phase 5, Release 2: client-editable, no preserve-on-edit
            # needed -- whatever the reviewer's own edit sends is correct.
            enterprise_system_id=req.constraints.enterprise_system_id,
        ),
        metadata=Metadata(
            owner=req.metadata.owner,
            created_by=req.metadata.created_by,
            tags=tuple(req.metadata.tags),
        ),
        audit=audit,
    )


def _record_to_response(row) -> RuntimePolicyResponse:
    content: dict[str, Any] = row.content
    return RuntimePolicyResponse(
        policy_key=str(row.policy_key),
        version=row.version,
        status=row.status,
        name=content["name"],
        description=content.get("description"),
        scope=ScopeSchema(**content["scope"]),
        conditions=[ConditionSchema(**c) for c in content["conditions"]["all"]],
        effect=content["effect"],
        constraints=ConstraintsSchema(**content["constraints"]),
        metadata=MetadataSchema(**content["metadata"]),
        audit=content.get("audit"),
        bundle_id=row.bundle_id,
        bundle_hash=row.bundle_hash,
        created_at=row.created_at,
    )


@router.get("/vocabulary")
def get_vocabulary():
    """The active adapter's known actions, so the frontend never
    hardcodes its own copy (the exact drift bug DOMAIN_REFACTOR_PLAN.md's
    item 5 already named for the existing Runtime Decisions page)."""
    return {"actions": sorted(FINANCIAL_VOCABULARY.known_actions)}


@router.get("", response_model=list[RuntimePolicyResponse])
def list_policies(status: str | None = None, db: Session = Depends(get_db)):
    return [_record_to_response(r) for r in svc.list_latest_policies(db, status=status)]


@router.get("/{policy_key}", response_model=RuntimePolicyResponse)
def get_policy(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    try:
        row = svc.get_latest(db, policy_key)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    return _record_to_response(row)


@router.get("/{policy_key}/versions", response_model=list[RuntimePolicyResponse])
def get_versions(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    try:
        rows = svc.list_versions(db, policy_key)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    return [_record_to_response(r) for r in rows]


@router.get("/{policy_key}/versions/{version}", response_model=RuntimePolicyResponse)
def get_version(policy_key: uuid.UUID, version: int, db: Session = Depends(get_db)):
    try:
        row = svc.get_version(db, policy_key, version)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_version_not_found")
    return _record_to_response(row)


@router.post(
    "", response_model=RuntimePolicyResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_CREATE))],
)
def create_policy(body: RuntimePolicyRequest, db: Session = Depends(get_db)):
    audit = AuditTrail(created=datetime.now(timezone.utc))
    policy = _build_runtime_policy(
        body, policy_id=str(uuid.uuid4()), version=1, status=PolicyStatus.DRAFT, audit=audit
    )
    row = svc.create_policy(db, policy)
    return _record_to_response(row)


@router.put(
    "/{policy_key}", response_model=RuntimePolicyResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def edit_policy(policy_key: uuid.UUID, body: RuntimePolicyRequest, db: Session = Depends(get_db)):
    try:
        latest = svc.get_latest(db, policy_key)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")

    now = datetime.now(timezone.utc)
    prior_audit = latest.content.get("audit") or {}
    original_created = prior_audit.get("created")
    audit = AuditTrail(
        created=datetime.fromisoformat(original_created) if original_created else now,
        modified=now,
    )
    prior_constraints = latest.content.get("constraints") or {}
    policy = _build_runtime_policy(
        body, policy_id=str(policy_key), version=latest.version + 1, status=PolicyStatus.DRAFT, audit=audit,
        preserve_authority_id=prior_constraints.get("authority_id"),
        preserve_mandate_id=prior_constraints.get("mandate_id"),
    )
    row = svc.edit_policy(db, policy_key, policy)
    return _record_to_response(row)


@router.post(
    "/{policy_key}/submit-for-review",
    response_model=RuntimePolicyResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def submit_for_review(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    try:
        row = svc.submit_for_review(db, policy_key)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _record_to_response(row)


@router.post(
    "/{policy_key}/approve",
    response_model=RuntimePolicyResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def approve_policy(
    policy_key: uuid.UUID,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
):
    try:
        row = svc.approve(
            db, policy_key, approver=body.approver,
            approver_user_id=session_user.id if session_user else None,
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _record_to_response(row)


@router.post(
    "/{policy_key}/reject",
    response_model=RuntimePolicyResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def reject_policy(
    policy_key: uuid.UUID,
    body: RejectRequest,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
):
    try:
        row = svc.reject(
            db, policy_key, reviewer=body.reviewer, reason=body.reason,
            reviewer_user_id=session_user.id if session_user else None,
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _record_to_response(row)


@router.post(
    "/{policy_key}/compile", response_model=CompileResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_EDIT))],
)
def compile_policy(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    try:
        outcome = svc.compile_policy(db, policy_key)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return CompileResponse(
        ok=outcome.ok,
        errors=[
            CompilerErrorSchema(code=e.code, message=e.message, policy_id=e.policy_id, path=e.path)
            for e in outcome.diagnostics.errors
        ],
        bundle_id=outcome.bundle_id,
        bundle_hash=outcome.bundle_hash,
    )


@router.post("/{policy_key}/dry-run", response_model=DryRunResponse)
def dry_run_policy(policy_key: uuid.UUID, body: DryRunRequest, db: Session = Depends(get_db)):
    try:
        row = svc.get_latest(db, policy_key)
        sample_input = {
            "intent": {"action": body.action, "resource": body.resource, **body.context},
            "agent": {"acting_for_principal_id": body.principal},
        }
        result = svc.dry_run_policy(db, policy_key, sample_input, opa_url=_opa_url())
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")

    if result.requires_review:
        decision = "HUMAN_REVIEW"
    elif result.allow and not result.deny:
        decision = "ALLOW"
    elif result.deny:
        decision = "DENY"
    else:
        decision = "HUMAN_REVIEW"

    # Evidence Required is read directly from this version's own
    # Constraints, not computed: row.content is already the exact dict
    # schema.to_dict() produced, so this needs no re-parsing through
    # from_dict() just to read one field back out.
    evidence_required = row.content["constraints"]["evidence_required"]

    return DryRunResponse(
        decision=decision,
        allow=result.allow,
        deny=result.deny,
        requires_review=result.requires_review,
        evaluated_mandates=result.evaluated_mandates,
        review_reason=result.review_reason,
        deny_reason=result.deny_reason,
        evidence_required=evidence_required,
    )


@router.post(
    "/{policy_key}/deploy", response_model=DeployResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def deploy_policy(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    try:
        outcome = svc.deploy_policy(db, policy_key, opa_url=_opa_url())
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")
    except BundleChangedSinceCompileError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except UnexpectedActiveWriterError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return DeployResponse(
        bundle_id=outcome.bundle_id, bundle_hash=outcome.bundle_hash, deployed_at=outcome.deployed_at,
        authority_id=outcome.authority_id, mandate_id=outcome.mandate_id,
    )


@router.get("/{policy_key}/diff", response_model=DiffResponse)
def diff_versions(policy_key: uuid.UUID, from_version: int, to_version: int, db: Session = Depends(get_db)):
    try:
        result = svc.diff_versions(db, policy_key, from_version, to_version)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_version_not_found")
    return DiffResponse(
        conditions=[
            {
                "kind": c.kind,
                "field": c.field,
                "operator": c.operator,
                "old_value": c.old_value,
                "new_value": c.new_value,
            }
            for c in result.conditions
        ],
        scope_changed=result.scope_changed,
        effect_changed=result.effect_changed,
        constraints_changed=result.constraints_changed,
        affected_agents=result.affected_agents,
        affected_policies=result.affected_policies,
        risk_impact=result.risk_impact,
        risk_reason=result.risk_reason,
    )
