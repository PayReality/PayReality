"""Decision Intelligence: Feature "cross-workflow reports and real
exports". Deliberately its own router, not added onto workflows.py (the
existing `/workflows/{id}/overview`) or questions.py/replays.py -- a real
file download (`GET .../export`) sits right next to a `GET .../{id}`
retrieval in neither of those routers' own URL shapes, and placing an
`/export` path under `questions.py` specifically risks colliding with
FastAPI's path-matching against `GET /questions/{question_id}` (a literal
"export" would otherwise be parsed as a UUID and 422, not routed here) --
keeping every real report/export endpoint under its own `/reports` prefix
sidesteps that entirely rather than depending on declaration order.

RBAC: every endpoint here is gated on `DI_REPORT_VIEW`, per the brief --
the same permission the existing per-workflow overview already uses."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.decision_intelligence.csv_export import build_csv
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import OrganizationOverviewResponse
from app.services import di_report_service
from app.services.di_replay_service import ReplayRunNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/reports", tags=["decision-intelligence"])


@router.get(
    "/organization-overview", response_model=OrganizationOverviewResponse,
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def get_organization_overview(
    organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    return di_report_service.get_organization_overview(db, organization.id)


@router.get(
    "/questions/export",
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def export_priority_questions(
    workflow_id: UUID | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """A real downloadable CSV file (`text/csv`, a real `Content-
    Disposition: attachment` header), not a JSON payload -- columns: id,
    title, status, priority_score, owner_user_id, linked_pattern_count,
    linked_case_count. Every user-entered text cell is run through the
    spreadsheet-formula-injection guard (csv_export.sanitize_csv_cell) on
    the way out; the stored data itself is never touched."""
    rows = di_report_service.get_priority_questions_export_rows(db, organization.id, workflow_id=workflow_id)
    csv_text = build_csv(di_report_service.PRIORITY_QUESTIONS_EXPORT_HEADER, rows)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="priority_questions.csv"'},
    )


@router.get(
    "/replays/{replay_run_id}/export",
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def export_replay_results(
    replay_run_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """A real downloadable CSV of one Replay run's per-case results:
    case_id, case_external_ref, baseline_decision, proposed_decision,
    outcome_category, notes. Same formula-injection guard as the
    Priority Questions export above, applied to `notes` and any string
    cell."""
    try:
        rows = di_report_service.get_replay_results_export_rows(db, replay_run_id, organization.id)
    except ReplayRunNotFoundError:
        raise HTTPException(status_code=404, detail="replay_run_not_found")
    csv_text = build_csv(di_report_service.REPLAY_RESULTS_EXPORT_HEADER, rows)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="replay_{replay_run_id}_results.csv"'},
    )
