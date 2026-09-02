"""Developer Distribution & Sandbox v1: small, shared resource caps
applied only to Organizations with `environment == "sandbox"` -- never
to production, and never a security boundary of their own (that's
organization_id-scoped tenant isolation, unchanged). Each number is
deliberately generous enough that a real Quickstart or Integration Kit
run never hits it, and small enough that scripting abuse of a single
sandbox organization is pointless. Centralized here so the numbers have
one source of truth; each caller (agent_service, runtime_policy_service,
integration_identity_service) still runs its own natural count query --
there is no shared, generic "count entities" abstraction to keep this
small and legible.
"""

from sqlalchemy.orm import Session

from app.db.models import Organization

MAX_AGENTS_PER_SANDBOX = 5
MAX_POLICIES_PER_SANDBOX = 10
MAX_INTEGRATION_IDENTITIES_PER_SANDBOX = 3


class SandboxLimitExceededError(Exception):
    def __init__(self, resource: str, limit: int):
        self.resource = resource
        self.limit = limit
        super().__init__(f"sandbox limit reached: at most {limit} {resource} per sandbox organization")


def is_sandbox_organization(db: Session, organization_id) -> bool:
    """`organization_id` may be `None` for a couple of legacy pre-multi-
    tenant call sites elsewhere in this codebase -- always treated as
    "not sandbox" (i.e. uncapped), matching how those call sites already
    predate the Organization concept entirely."""
    if organization_id is None:
        return False
    organization = db.get(Organization, organization_id)
    return organization is not None and organization.environment == "sandbox"
