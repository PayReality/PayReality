"""Decision Intelligence: CSV case import (DIImportJob). See
di_import_service.py's own module docstring for the partial-success
transaction design, and csv_import.py for the column-mapping/row
validation rules.

RBAC: the upload itself is gated on `DI_CASE_MANAGE` -- the exact same
permission manual case creation (`POST /cases`) uses, per this feature's
own brief, since a CSV import is just a bulk form of the same mutating
action. The two read endpoints below are gated on `DI_CASE_VIEW` instead
-- a judgment call (the brief only specified the upload's own gate):
consistent with every other DI resource in this module, where VIEW
permissions cover read endpoints and MANAGE permissions cover writes
(cases.py, questions.py, ...), rather than requiring MANAGE just to check
an import's status."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.decision_intelligence.csv_import import InvalidColumnMappingError
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import ImportJobListResponse, ImportJobResponse
from app.services import di_import_service
from app.services.di_import_service import EmptyImportFileError, ImportJobNotFoundError
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/imports", tags=["decision-intelligence"])


@router.post(
    "", response_model=ImportJobResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_CASE_MANAGE))],
)
async def create_import_job(
    file: UploadFile,
    workflow_id: UUID = Form(...),
    column_mapping: str = Form("{}"),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Multipart upload: `file` (the CSV), `workflow_id`, and
    `column_mapping` (a JSON-encoded object, e.g.
    `{"Ref": "external_ref", "Decision": "human_decision", "Notes":
    "exclude"}` -- any CSV header not named here becomes a `facts` key
    automatically). A JSON string inside a multipart form field, rather
    than a nested JSON body, because multipart/form-data has no native
    way to carry a structured object alongside a binary file part; this
    is the same shape FastAPI's own docs recommend for "file plus
    metadata" uploads.

    File-size limit: `di_import_service.MAX_IMPORT_FILE_BYTES` (10 MiB) --
    see that module's own docstring for why this is a brand-new limit,
    not a reused existing convention (none was found)."""
    raw = await file.read()
    if len(raw) > di_import_service.MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="import_file_too_large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="import_file_must_be_utf8_csv")

    try:
        mapping = json.loads(column_mapping) if column_mapping else {}
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="column_mapping_must_be_json")
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=422, detail="column_mapping_must_be_a_json_object")

    try:
        return di_import_service.import_cases_from_csv(
            db, organization.id, workflow_id, user.id, file.filename or "import.csv", text, mapping,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    except EmptyImportFileError:
        raise HTTPException(status_code=422, detail="csv_file_has_no_data_rows")
    except InvalidColumnMappingError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get(
    "", response_model=ImportJobListResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_import_jobs(
    workflow_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    jobs, total = di_import_service.list_import_jobs(
        db, organization.id, workflow_id=workflow_id, limit=limit, offset=offset
    )
    return ImportJobListResponse(import_jobs=jobs, total=total, limit=limit, offset=offset)


@router.get(
    "/{job_id}", response_model=ImportJobResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def get_import_job(
    job_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        return di_import_service.get_import_job(db, job_id, organization.id)
    except ImportJobNotFoundError:
        raise HTTPException(status_code=404, detail="import_job_not_found")
