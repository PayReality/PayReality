"""RuntimePolicy: the canonical internal representation every authoring
method (guided wizard, manual Policy Studio, AI policy translation,
direct API) must eventually produce, and the only thing the Runtime
Authority Engine should ever consume. See RUNTIME_POLICY_LANGUAGE.md for
why this exists and how it relates to today's Authority/Mandate model.

This module imports nothing from the database, FastAPI, or any authoring
mechanism. It has no knowledge that a wizard or an AI extraction pass
exists. That is the point: a RuntimePolicy is a plain, framework-agnostic
value, constructed and validated identically regardless of where it came
from, matching the same "no DB dependency" discipline
domain/compiler/compiler.py already holds itself to.

A RuntimePolicy is immutable. Editing one produces a new RuntimePolicy
with an incremented version, not a mutation of the existing value: a
policy version is a fact about what was authored and approved at a point
in time, not a row updated in place.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.constraints import Constraints
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail, Metadata


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPILED = "compiled"
    ACTIVE = "active"
    RETIRED = "retired"
    # Runtime Policy Lifecycle (Phase 5, RUNTIME_POLICY_LIFECYCLE.md): the
    # one genuinely new terminal status this phase adds. Additive only --
    # every existing transition (draft/pending_review/approved/rejected/
    # compiled/active/retired) and everything that checks for those exact
    # string values is completely unaffected, since nothing before this
    # phase could ever produce "archived." "Superseded" is deliberately
    # NOT a stored status: a retired RuntimePolicyRecord that has a newer
    # active sibling of the same policy_key is presented as "Superseded"
    # by services/runtime_policy_lifecycle_service.py's read-side label,
    # computed on the fly -- not a second status value for what
    # deploy_policy already correctly marks "retired," to avoid touching
    # that already-working transition at all. "Deprecated" is likewise
    # not a status: it is a flag (RuntimePolicyRecord.deprecated_at) on
    # an ACTIVE row, since a deprecated-but-not-yet-retired policy must
    # keep being enforced until its scheduled retirement -- changing its
    # status away from "active" would silently stop Runtime Authority
    # from enforcing it, which is explicitly not what "scheduled for
    # retirement" means.
    ARCHIVED = "archived"


@dataclass(frozen=True)
class Scope:
    """Who this RuntimePolicy delegates authority to, and over what.

    `principal` and `action` are required: a policy that doesn't say who
    it's for and what it governs isn't a policy. `agent` narrows a policy
    to one specific agent identity rather than every agent acting for a
    principal (a genuine extension beyond today's Authority/Mandate
    model, which scopes by principal + action only). `resource` is the
    generic successor to today's finance-specific `counterparty`
    (DOMAIN_ABSTRACTION.md's classification table names this exact
    generalization).
    """

    principal: str
    action: str
    agent: str | None = None
    resource: str | None = None


@dataclass(frozen=True)
class RuntimePolicy:
    id: str
    name: str
    version: int
    status: PolicyStatus
    scope: Scope
    conditions: ConditionSet
    effect: Effect
    description: str | None = None
    constraints: Constraints = field(default_factory=Constraints)
    metadata: Metadata = field(default_factory=Metadata)
    audit: AuditTrail | None = None
