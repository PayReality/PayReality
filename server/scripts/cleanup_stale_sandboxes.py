#!/usr/bin/env python3
"""Developer Distribution & Sandbox v1: archives sandbox Organizations
older than a threshold. This is the "smallest safe mechanism" this
milestone builds for sandbox data lifecycle -- a real, callable,
DB-level operation, but deliberately NOT wired into any scheduler
(cron, a GitHub Actions scheduled workflow, an Azure WebJob, or this
codebase's own internal `process_due_schedules` dispatcher). Running it
regularly is an explicit, disclosed operational requirement, not
something this milestone claims happens automatically.

Runs the real, unmodified deactivate -> archive sequence
(`organization_lifecycle_service.archive_stale_sandbox_organizations`,
which itself calls `deactivate_organization`/`archive_organization`
unchanged) -- never a direct status write. Only ever touches
Organizations with `environment == "sandbox"`; a production Organization
is never a candidate regardless of age.

Usage (run where DATABASE_URL already points at the real database --
same convention as running Alembic migrations, not a new one):

    cd server
    python scripts/cleanup_stale_sandboxes.py --older-than-days 14
    python scripts/cleanup_stale_sandboxes.py --older-than-days 14 --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.services import organization_lifecycle_service as org_svc  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--older-than-days", type=int, required=True)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be archived without actually archiving anything.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dry_run:
            stale = org_svc.list_stale_sandbox_organizations(db, args.older_than_days)
            print(f"Would archive {len(stale)} stale sandbox organization(s):")
            for organization in stale:
                print(f"  {organization.id}  {organization.name}  created_at={organization.created_at}")
        else:
            archived = org_svc.archive_stale_sandbox_organizations(db, args.older_than_days)
            print(f"Archived {len(archived)} stale sandbox organization(s):")
            for organization in archived:
                print(f"  {organization.id}  {organization.name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
