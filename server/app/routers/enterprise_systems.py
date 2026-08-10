from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.enterprise_system import CreateEnterpriseSystemRequest, EnterpriseSystemResponse
from app.services import enterprise_system_service as svc

router = APIRouter(prefix="/v1/enterprise-systems", tags=["enterprise-systems"])


@router.post(
    "",
    response_model=EnterpriseSystemResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.INTEGRATIONS_MANAGE))],
)
def create_enterprise_system(
    body: CreateEnterpriseSystemRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Authority-as-a-continuous-object, Stage J: registers that a
    downstream system exists, nothing more. `status` is left at the
    column default ('configuration_required') -- never set to
    'connected' here, since no connector code exists to earn that
    state (Organisation Settings' Integrations tab already established
    this exact honesty pattern for Azure OpenAI/AWS Bedrock)."""
    return svc.create_enterprise_system(db, organization.id, name=body.name, type=body.type)


@router.get(
    "",
    response_model=list[EnterpriseSystemResponse],
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def list_enterprise_systems(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return svc.list_enterprise_systems(db, organization.id)
