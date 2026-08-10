"""Constraints: qualifiers on a RuntimePolicy beyond its match conditions.

A Condition (conditions.py) is evaluated against an incoming Intent's
fields at decision time. A Constraint is a property of the policy itself,
declared at authoring time, that shapes how the policy may be used
regardless of what any single Intent contains.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Constraints:
    delegated_by: str | None = None
    expires: datetime | None = None
    # Every decision produces Evidence unconditionally today (see
    # PRODUCT.md / ARCHITECTURE.md); this field exists so a RuntimePolicy
    # can eventually express an exception to that, but nothing reads or
    # enforces it yet (see RUNTIME_POLICY_LANGUAGE.md's migration path).
    # Defaults to True to match today's actual unconditional behavior.
    evidence_required: bool = True
    risk_level: RiskLevel | None = None
    # Authority-as-a-continuous-object, Stage G: `delegated_by` above
    # stays exactly what every existing reader displays and what a
    # reviewer can still type freely. `authority_id` is set at promotion
    # time when the candidate's delegation resolves to a real Principal
    # (a real `authorities` row is created citing that Principal and its
    # source corpus). `mandate_id` is set later, at publish/deploy time,
    # once a real Policy bundle exists for the Mandate to reference --
    # Mandate.policy_id is NOT NULL, so a Mandate cannot exist before
    # that moment. Both are string ids (not UUID) to match every other
    # id already stored in this JSON-serialized dataclass.
    authority_id: str | None = None
    mandate_id: str | None = None
    # Phase 5, Release 2 (Enterprise System binding): reviewer-configured
    # at authoring time, the same trust model as delegated_by/risk_level
    # above -- a human who knows this policy's action reaches e.g. the
    # Finance ERP sets it explicitly. Never inferred, never guessed:
    # runtime_policy_service.resolve_enterprise_system reads this value
    # back at decision time and only assigns Decision.enterprise_system_id
    # when it points at a real, still-existing EnterpriseSystem row.
    enterprise_system_id: str | None = None
