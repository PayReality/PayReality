from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.assurance import AssuranceSummaryResponse
from app.services import assurance_service

router = APIRouter(prefix="/v1/assurance", tags=["assurance"])


@router.get(
    "/summary",
    response_model=AssuranceSummaryResponse,
    dependencies=[Depends(require_permission(Permission.ASSURANCE_VIEW))],
)
def get_assurance_summary(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Product Experience Remediation Milestone 1, Phase 6: one bounded,
    organisation-scoped call replacing the previous frontend pattern
    (LiveAssurance.tsx fetching every Agent and every Evidence record
    and reducing outcome counts client-side, with no pagination or time
    window at all). Every field is a real server-side aggregate -- see
    assurance_service.get_summary for exactly which query backs each
    one."""
    return assurance_service.get_summary(db, organization.id)
