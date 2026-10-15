"""Decision Intelligence: CSV case import (DIImportJob).

Deliberately synchronous and deliberately PARTIAL SUCCESS, not all-or-
nothing (the brief explicitly left this choice open): every row that
passes validation (app.domain.decision_intelligence.csv_import) becomes a
real, persisted DICase, and every row that doesn't is reported, with its
own specific reason(s), in the job's `row_errors` -- a CSV with 95 good
rows and 5 malformed ones imports the 95 rather than failing the whole
file and forcing a human to resubmit it. This is more useful at this
product's scale (a human reviewing and re-uploading a hand-edited
spreadsheet) than strict atomicity would be; the atomicity this module
DOES guarantee is narrower but real: the DIImportJob row itself and every
DICase row it produced are committed together, in one transaction, so the
job's own `valid_rows`/`invalid_rows`/`row_errors` summary can never
drift from what was actually inserted (no world where the job claims 10
cases imported but only 9 exist, or vice versa).

No file-size convention existed anywhere in this codebase to reuse
(confirmed: no `upload_limits.py` exists under `server/app/domain/`
anywhere, and the sibling AI Authority Builder corpus upload endpoint,
`POST /v1/ai-authority-builder/corpora`, enforces no file-size limit at
all) -- the brief's premise that one exists was checked and found false.
`MAX_IMPORT_FILE_BYTES` below is this feature's own new, explicit limit
(10 MiB), chosen as a generous bound for a CSV of case rows at this
product's own documented demo scale, enforced by the router before this
service ever sees the bytes."""

import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DICase, DIImportJob
from app.domain.decision_intelligence.csv_import import InvalidColumnMappingError, validate_and_map_csv_rows
from app.services import di_audit_service, di_workflow_service

MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB -- see module docstring


class ImportJobNotFoundError(Exception):
    pass


class EmptyImportFileError(Exception):
    pass


def _existing_external_refs(db: Session, workflow_id: uuid.UUID) -> set[str]:
    stmt = select(DICase.external_ref).where(
        DICase.workflow_id == workflow_id, DICase.external_ref.is_not(None)
    )
    return {ref for ref in db.scalars(stmt) if ref}


def import_cases_from_csv(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    filename: str,
    csv_text: str,
    column_mapping: dict[str, str],
) -> DIImportJob:
    """Parses `csv_text` (already decoded by the router), validates/maps
    every row against `column_mapping`, inserts a real DICase for every
    valid row, and returns the completed DIImportJob. Raises
    WorkflowNotFoundError (propagated to the router, matching every other
    DI service's own convention) before anything else if `workflow_id`
    doesn't resolve in this organization -- an import can never be filed
    against another organization's workflow, same rule `di_case_service.
    create_case` already enforces for a single manually-created case."""
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows:
        raise EmptyImportFileError("csv_file_has_no_data_rows")

    job = DIImportJob(
        organization_id=organization_id,
        workflow_id=workflow_id,
        status="validating",
        filename=filename,
        total_rows=len(rows),
        created_by_user_id=created_by_user_id,
    )
    db.add(job)
    db.flush()

    existing_refs = _existing_external_refs(db, workflow_id)
    results = validate_and_map_csv_rows(rows, column_mapping, existing_refs)  # may raise InvalidColumnMappingError

    row_errors: list[dict] = []
    valid_count = 0
    for result in results:
        if result.is_valid:
            case = result.case
            db.add(
                DICase(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                    created_by_user_id=created_by_user_id,
                    external_ref=case.external_ref,
                    facts=case.facts or {},
                    human_decision=case.human_decision,
                    escalation_reason=case.escalation_reason,
                    outcome=case.outcome,
                )
            )
            valid_count += 1
        else:
            row_errors.append({"row_number": result.row_number, "errors": result.errors})

    job.status = "completed"
    job.valid_rows = valid_count
    job.invalid_rows = len(row_errors)
    job.row_errors = row_errors
    job.completed_at = datetime.now(timezone.utc)

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="import", entity_type="DIImportJob", entity_id=job.id,
        new_value={
            "filename": filename,
            "workflow_id": str(workflow_id),
            "total_rows": job.total_rows,
            "valid_rows": job.valid_rows,
            "invalid_rows": job.invalid_rows,
        },
    )
    # One audit event per completed job, never per row (brief's own
    # requirement) -- row-level detail lives in job.row_errors instead.

    db.commit()
    db.refresh(job)
    return job


def get_import_job(db: Session, job_id: uuid.UUID, organization_id: uuid.UUID) -> DIImportJob:
    job = db.get(DIImportJob, job_id)
    if job is None or job.organization_id != organization_id:
        raise ImportJobNotFoundError(str(job_id))
    return job


def list_import_jobs(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIImportJob], int]:
    stmt = select(DIImportJob).where(DIImportJob.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIImportJob.workflow_id == workflow_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIImportJob.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


__all__ = [
    "MAX_IMPORT_FILE_BYTES",
    "ImportJobNotFoundError",
    "EmptyImportFileError",
    "InvalidColumnMappingError",
    "import_cases_from_csv",
    "get_import_job",
    "list_import_jobs",
]
