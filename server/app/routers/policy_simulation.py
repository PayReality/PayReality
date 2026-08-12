"""Runtime Policy Simulator (Authority Intelligence Program, Phase 4,
POLICY_SIMULATOR.md). Every endpoint here is read-only with respect to
Runtime Authority itself: none of them ever create, edit, compile, or
deploy a RuntimePolicy, and none of them ever write a Decision, an
Evidence row, or a Mandate. The only persistence anywhere in this router
is a saved SimulationScenario's own definition (create_scenario) --
never a simulated outcome.

Gated by Permission.RUNTIME_POLICY_VIEW throughout: simulating against
an existing policy version is an exploratory, read-only action on that
policy, not an edit/publish action, so it does not require the stronger
RUNTIME_POLICY_EDIT/PUBLISH permissions Policy Studio's own mutating
endpoints require.
"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user_if_session, require_permission
from app.domain.compiler_v2.dry_run import DryRunError
from app.domain.rbac.permissions import Permission
from app.schemas.policy_simulation import (
    AuthorityTraceStepResponse,
    BatchRowResponse,
    BatchSimulationResponse,
    ConditionEvaluationResponse,
    CreateScenarioRequest,
    EvidencePreviewResponse,
    RuleEvaluationResponse,
    ScenarioResponse,
    ScenarioRunResponse,
    SimulationInputRequest,
    SimulationResponse,
)
from app.services import policy_simulation_service as svc
from app.services.policy_simulation_service import (
    CompilationRequiredError,
    RuntimePolicyNotFoundError,
    ScenarioNotFoundError,
    SimulationInput,
)

router = APIRouter(prefix="/v1/policy-simulation", tags=["policy-simulation"])

_VALID_OUTCOMES = ("ALLOW", "DENY", "HUMAN_REVIEW")


def _to_sim_input(body: SimulationInputRequest) -> SimulationInput:
    return SimulationInput(
        principal=body.principal, action=body.action, resource=body.resource,
        amount=body.amount, currency=body.currency, agent_name=body.agent_name, context=body.context,
    )


def _rule_to_response(r) -> RuleEvaluationResponse:
    return RuleEvaluationResponse(
        policy_id=r.policy_id, policy_name=r.policy_name, principal=r.principal, action=r.action,
        effect=r.effect, scope_matched=r.scope_matched, matched=r.matched, summary=r.summary,
        conditions=[
            ConditionEvaluationResponse(
                field=c.field, operator=c.operator, expected_value=c.expected_value,
                actual_value=c.actual_value, passed=c.passed,
            )
            for c in r.conditions
        ],
    )


def _result_to_response(result) -> SimulationResponse:
    return SimulationResponse(
        decision=result.decision, policy_key=result.policy_key, policy_name=result.policy_name,
        policy_version=result.policy_version, policy_bundle_hash=result.policy_bundle_hash,
        generated_at=result.generated_at, review_reason=result.review_reason, deny_reason=result.deny_reason,
        rules=[_rule_to_response(r) for r in result.rules],
        authority_trace=[AuthorityTraceStepResponse(label=s.label, detail=s.detail) for s in result.authority_trace],
        evidence_preview=EvidencePreviewResponse(
            decision=result.evidence_preview.decision, policy_version=result.evidence_preview.policy_version,
            policy_bundle_hash=result.evidence_preview.policy_bundle_hash,
            principal=result.evidence_preview.principal, action=result.evidence_preview.action,
            resource=result.evidence_preview.resource, evaluated_at=result.evidence_preview.evaluated_at,
            receipt_hash=result.evidence_preview.receipt_hash, preview=result.evidence_preview.preview,
        ),
    )


def _scenario_to_response(row) -> ScenarioResponse:
    return ScenarioResponse(
        id=str(row.id), policy_key=str(row.policy_key), name=row.name,
        input=SimulationInputRequest(**row.input), expected_outcome=row.expected_outcome,
        created_by=row.created_by, created_at=row.created_at,
    )


@router.post(
    "/{policy_key}/simulate", response_model=SimulationResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def simulate(policy_key: uuid.UUID, body: SimulationInputRequest, db: Session = Depends(get_db)):
    """Task: Simulation Execution. Runs the exact same OPA evaluation
    Runtime Authority uses in production, isolated from it entirely
    (domain/compiler_v2/dry_run.py's already-verified mechanism) --
    never modifies the selected policy or any other, never persists
    anything."""
    try:
        result = svc.simulate(db, policy_key, _to_sim_input(body), opa_url=settings.opa_url)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")
    except DryRunError as e:
        raise HTTPException(status_code=502, detail=f"opa_evaluation_failed: {e}")
    return _result_to_response(result)


@router.post(
    "/{policy_key}/scenarios", response_model=ScenarioResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def create_scenario(
    policy_key: uuid.UUID, body: CreateScenarioRequest, db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
):
    """Task: Test Scenarios. Saves only the scenario's INPUT and
    expected outcome -- never a computed actual outcome, which is
    always derived live on every run (see run_scenario below)."""
    if body.expected_outcome not in _VALID_OUTCOMES:
        raise HTTPException(status_code=422, detail=f"expected_outcome must be one of {_VALID_OUTCOMES}")
    scenario = svc.create_scenario(
        db, policy_key, name=body.name, sim_input=_to_sim_input(body.input),
        expected_outcome=body.expected_outcome, created_by=session_user.name if session_user else None,
    )
    return _scenario_to_response(scenario)


@router.get(
    "/{policy_key}/scenarios", response_model=list[ScenarioResponse],
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def list_scenarios(policy_key: uuid.UUID, db: Session = Depends(get_db)):
    return [_scenario_to_response(s) for s in svc.list_scenarios(db, policy_key)]


@router.post(
    "/scenarios/{scenario_id}/run", response_model=ScenarioRunResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def run_scenario(scenario_id: uuid.UUID, db: Session = Depends(get_db)):
    """Task: Test Scenarios, "Actual". Re-runs the saved scenario's
    input against the policy's CURRENT state -- a scenario that passed
    yesterday can legitimately fail today if the policy changed; that
    is the entire point of saving it."""
    try:
        run_result = svc.run_scenario(db, scenario_id, opa_url=settings.opa_url)
    except ScenarioNotFoundError:
        raise HTTPException(status_code=404, detail="scenario_not_found")
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")
    except DryRunError as e:
        raise HTTPException(status_code=502, detail=f"opa_evaluation_failed: {e}")

    return ScenarioRunResponse(
        scenario_id=run_result.scenario_id, scenario_name=run_result.scenario_name,
        expected_outcome=run_result.expected_outcome, actual_outcome=run_result.actual_outcome,
        passed=run_result.passed, result=_result_to_response(run_result.result),
    )


@router.post(
    "/{policy_key}/batch", response_model=BatchSimulationResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
async def batch_simulate(policy_key: uuid.UUID, file: UploadFile, db: Session = Depends(get_db)):
    """Task: Batch Simulation. CSV columns: `principal`, `action`
    (both required), `resource`, `amount`, `currency` (all optional) --
    any other column is passed through as flat Runtime Authority
    Context. Never persists a single row's decision; only aggregate
    counts and a capped sample are returned."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="batch_file_must_be_utf8_csv")

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=422, detail="batch_file_has_no_rows")

    try:
        result = svc.run_batch(db, policy_key, rows, opa_url=settings.opa_url)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")
    except DryRunError as e:
        raise HTTPException(status_code=502, detail=f"opa_evaluation_failed: {e}")

    return BatchSimulationResponse(
        total=result.total, allowed=result.allowed, denied=result.denied, escalated=result.escalated,
        errors=result.errors, sample_truncated=result.sample_truncated,
        policy_version=result.policy_version, policy_bundle_hash=result.policy_bundle_hash,
        sample_rows=[
            BatchRowResponse(row_number=r.row_number, principal=r.principal, action=r.action,
                              decision=r.decision, error=r.error)
            for r in result.sample_rows
        ],
    )
