"""AI-assisted discovery of recurring uncertainty patterns and candidate
priority questions (DIDiscoveryRun / DIDiscoverySuggestion). Provider
runtime selection mirrors routers/ai_policy_builder.py's own `_provider()`
exactly for the two providers this feature ships (fake/claude): empty
config -> Fake (needs no API key, the path most deployments actually run),
`ANTHROPIC_API_KEY` set -> Claude. Unlike the sibling AI features, there is
deliberately no Azure AI Foundry branch here -- no AzureFoundryDiscoveryProvider
exists yet (see domain/decision_intelligence/ai_discovery/__init__.py's own
docstring) -- so if `azure_ai_foundry_endpoint` happens to be set in an
environment, discovery still correctly falls through to Claude/Fake rather
than silently claiming a Foundry call that never happened.

Accept/dismiss gating (`require_permission_for_suggestion_kind`):
the brief requires accepting/dismissing a 'pattern'-kind suggestion to need
the same permission as manually creating a Pattern (DI_PATTERN_MANAGE), and
a 'question'-kind suggestion the same as manually creating a Question
(DI_QUESTION_MANAGE) -- a genuinely data-dependent permission decision this
codebase's existing `require_permission(single_permission)` dependency
factory has no way to express (every other route in this codebase gates on
one fixed permission, never one chosen per-request from the resource being
acted on). The dependency below deliberately duplicates
`require_permission`'s own operator-key/session-role resolution exactly
(see its docstring in app/dependencies.py) rather than inventing a looser
check, then picks the one permission that actually matters for this
specific suggestion's `kind` before deciding."""

import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DIDiscoverySuggestion, DIPattern, Organization, User
from app.db.session import get_db
from app.dependencies import _bearer_token, get_current_organization, get_current_user, require_permission
from app.domain.decision_intelligence.ai_discovery.claude_provider import ClaudeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.fake_provider import FakeDiscoveryProvider
from app.domain.rbac.permissions import Permission, has_permission
from app.schemas.decision_intelligence import (
    AcceptSuggestionResponse,
    DiscoveryRunDetailResponse,
    DiscoveryRunListResponse,
    DiscoveryRunResponse,
    DiscoverySuggestionResponse,
    PatternResponse,
    QuestionResponse,
)
from app.services import auth_service, di_discovery_service as svc
from app.services.di_discovery_service import (
    DiscoveryRunNotFoundError,
    LinkedPatternNotAcceptedError,
    LinkedPatternNotFoundError,
    SuggestionNotFoundError,
    SuggestionNotPendingError,
)
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence", tags=["decision-intelligence"])


def _provider():
    if settings.anthropic_api_key:
        return ClaudeDiscoveryProvider(), "claude"
    return FakeDiscoveryProvider(), "fake"


def _run_to_response(run) -> DiscoveryRunResponse:
    return DiscoveryRunResponse.model_validate(run)


def _suggestion_to_response(suggestion) -> DiscoverySuggestionResponse:
    return DiscoverySuggestionResponse.model_validate(suggestion)


def _run_detail(db: Session, run) -> DiscoveryRunDetailResponse:
    suggestions = svc.list_suggestions_for_run(db, run.id, run.organization_id)
    return DiscoveryRunDetailResponse(
        discovery_run=_run_to_response(run),
        suggestions=[_suggestion_to_response(s) for s in suggestions],
    )


@router.post(
    "/workflows/{workflow_id}/discover", response_model=DiscoveryRunDetailResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_PATTERN_MANAGE))],
)
def discover(
    workflow_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Runs synchronously: the response already carries the completed (or
    failed) run's own suggestions, matching replays.py's own
    create_replay docstring for why this is the right choice at this
    product's scale."""
    provider, provider_used = _provider()
    try:
        run = svc.create_and_run_discovery(db, organization.id, workflow_id, user.id, provider, provider_used)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    return _run_detail(db, run)


@router.get(
    "/workflows/{workflow_id}/discovery-runs", response_model=DiscoveryRunListResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_discovery_runs(
    workflow_id: UUID,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    runs, total = svc.list_discovery_runs(db, organization.id, workflow_id=workflow_id, limit=limit, offset=offset)
    return DiscoveryRunListResponse(
        discovery_runs=[_run_to_response(r) for r in runs], total=total, limit=limit, offset=offset
    )


@router.get(
    "/workflows/{workflow_id}/discovery-runs/{run_id}", response_model=DiscoveryRunDetailResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def get_discovery_run(
    workflow_id: UUID,
    run_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        run = svc.get_discovery_run(db, run_id, organization.id)
    except DiscoveryRunNotFoundError:
        raise HTTPException(status_code=404, detail="discovery_run_not_found")
    if run.workflow_id != workflow_id:
        # Same "cross-scope access looks like not-found" posture this
        # codebase already uses everywhere else -- never leak that a run
        # exists under a different workflow than the one in the URL.
        raise HTTPException(status_code=404, detail="discovery_run_not_found")
    return _run_detail(db, run)


def require_permission_for_suggestion_kind():
    """A `require_permission`-shaped dependency FACTORY (note the `()` at
    every call site below, matching `require_permission(permission)`'s own
    call convention exactly) rather than a fixed-permission dependency,
    because the one permission that applies here depends on data
    (`DIDiscoverySuggestion.kind`) `require_permission`'s own single-
    permission signature has no way to express. Named and shaped this way
    -- not just functionally equivalent -- specifically so
    tests/unit/test_route_permission_gates.py's own structural scan (which
    looks for "require_permission" in a dependency's `__qualname__`, since
    this codebase's convention is to prove gating by introspecting the
    real route table, not just by trusting a function's behavior) sees
    this for what it genuinely is: a real permission gate, not an
    unprotected route. Duplicates `require_permission`'s own operator-key/
    session-role resolution exactly (see its docstring in
    app/dependencies.py) rather than inventing a looser check."""

    async def _check(
        suggestion_id: UUID,
        x_payreality_operator_key: str | None = Header(None),
        authorization: str | None = Header(None),
        db: Session = Depends(get_db),
    ) -> None:
        if x_payreality_operator_key is not None:
            if not settings.admin_api_key:
                raise HTTPException(status_code=503, detail="operator_auth_not_configured")
            if not hmac.compare_digest(x_payreality_operator_key, settings.admin_api_key):
                raise HTTPException(status_code=401, detail="invalid_operator_key")
            return

        token = _bearer_token(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="authentication_required")

        role = auth_service.resolve_role_for_token(db, token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid_or_expired_credential")

        suggestion = db.get(DIDiscoverySuggestion, suggestion_id)
        # A missing/cross-org suggestion still needs *a* permission
        # decision here; the handler's own get_suggestion call resolves
        # the real 404 immediately afterward. Defaulting to
        # DI_PATTERN_MANAGE in that case never grants extra access: a
        # caller without it is still correctly rejected (403) before ever
        # learning whether the id exists.
        needed = (
            Permission.DI_QUESTION_MANAGE
            if suggestion is not None and suggestion.kind == "question"
            else Permission.DI_PATTERN_MANAGE
        )

        if not has_permission(role, needed):
            raise HTTPException(status_code=403, detail="permission_denied")

    return _check


@router.post(
    "/discovery-suggestions/{suggestion_id}/accept", response_model=AcceptSuggestionResponse,
    dependencies=[Depends(require_permission_for_suggestion_kind())],
)
def accept_suggestion(
    suggestion_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        created = svc.accept_suggestion(db, suggestion_id, organization.id, user.id)
    except SuggestionNotFoundError:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    except SuggestionNotPendingError as e:
        raise HTTPException(status_code=409, detail=f"suggestion_already_{e.status}")
    except LinkedPatternNotAcceptedError as e:
        raise HTTPException(
            status_code=400,
            detail=f"linked_pattern_suggestion_not_accepted: suggestion {e.linked_suggestion_id} is '{e.status}'",
        )
    except LinkedPatternNotFoundError:
        raise HTTPException(status_code=404, detail="linked_pattern_not_found")

    if isinstance(created, DIPattern):
        return AcceptSuggestionResponse(entity_type="pattern", pattern=PatternResponse.model_validate(created))
    return AcceptSuggestionResponse(entity_type="question", question=QuestionResponse.model_validate(created))


@router.post(
    "/discovery-suggestions/{suggestion_id}/dismiss", response_model=DiscoverySuggestionResponse,
    dependencies=[Depends(require_permission_for_suggestion_kind())],
)
def dismiss_suggestion(
    suggestion_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        suggestion = svc.dismiss_suggestion(db, suggestion_id, organization.id, user.id)
    except SuggestionNotFoundError:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    except SuggestionNotPendingError as e:
        raise HTTPException(status_code=409, detail=f"suggestion_already_{e.status}")
    return suggestion
