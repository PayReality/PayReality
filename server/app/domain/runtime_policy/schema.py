"""Canonical serialization for RuntimePolicy.

to_dict/from_dict round-trip a RuntimePolicy to and from a plain dict
(JSON-shaped: str/int/float/bool/list/dict only), for storage, API
responses, and hashing. canonical_json applies the same sorted-key,
no-incidental-whitespace discipline domain/compiler/compiler.py's
_canonical_bytes already requires of bundle_hash, so that comparing two
RuntimePolicy revisions or hashing one for integrity purposes is
reproducible byte-for-byte.

JSON_SCHEMA is a plain-dict JSON Schema description of the same shape,
kept here as documentation and a stable external contract, not wired to
any schema-validation library: this package has no third-party
dependencies, and validators.py's hand-written checks are the actual
source of truth for what's valid, not a generic schema validator.
"""

import json
from datetime import datetime
from typing import Any

from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail, Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _dt_from_str(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s is not None else None


def to_dict(policy: RuntimePolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "name": policy.name,
        "description": policy.description,
        "version": policy.version,
        "status": policy.status.value,
        "scope": {
            "principal": policy.scope.principal,
            "action": policy.scope.action,
            "agent": policy.scope.agent,
            "resource": policy.scope.resource,
        },
        "conditions": {
            "all": [
                {"field": c.field, "operator": c.operator.value, "value": c.value}
                for c in policy.conditions.all
            ]
        },
        "effect": policy.effect.value,
        "constraints": {
            "delegated_by": policy.constraints.delegated_by,
            "expires": _dt_to_str(policy.constraints.expires),
            "evidence_required": policy.constraints.evidence_required,
            "risk_level": policy.constraints.risk_level.value
            if policy.constraints.risk_level is not None
            else None,
            "authority_id": policy.constraints.authority_id,
            "mandate_id": policy.constraints.mandate_id,
            "enterprise_system_id": policy.constraints.enterprise_system_id,
        },
        "metadata": {
            "owner": policy.metadata.owner,
            "created_by": policy.metadata.created_by,
            "tags": list(policy.metadata.tags),
            "source_type": policy.metadata.source_type,
            "source_corpus_id": policy.metadata.source_corpus_id,
            "source_graph_approval_id": policy.metadata.source_graph_approval_id,
            "source_graph_version": policy.metadata.source_graph_version,
            "source_candidate_id": policy.metadata.source_candidate_id,
        },
        "audit": (
            {
                "created": _dt_to_str(policy.audit.created),
                "modified": _dt_to_str(policy.audit.modified),
                "approved": _dt_to_str(policy.audit.approved),
                "deployed": _dt_to_str(policy.audit.deployed),
                "modified_by": policy.audit.modified_by,
                "approved_by": policy.audit.approved_by,
                "deployed_by": policy.audit.deployed_by,
            }
            if policy.audit is not None
            else None
        ),
    }


def from_dict(data: dict[str, Any]) -> RuntimePolicy:
    scope_data = data["scope"]
    conditions_data = data.get("conditions") or {"all": []}
    constraints_data = data.get("constraints") or {}
    metadata_data = data.get("metadata") or {}
    audit_data = data.get("audit")

    return RuntimePolicy(
        id=data["id"],
        name=data["name"],
        description=data.get("description"),
        version=data["version"],
        status=PolicyStatus(data["status"]),
        scope=Scope(
            principal=scope_data["principal"],
            action=scope_data["action"],
            agent=scope_data.get("agent"),
            resource=scope_data.get("resource"),
        ),
        conditions=ConditionSet(
            all=tuple(
                Condition(field=c["field"], operator=Operator(c["operator"]), value=c["value"])
                for c in conditions_data.get("all", [])
            )
        ),
        effect=Effect(data["effect"]),
        constraints=Constraints(
            delegated_by=constraints_data.get("delegated_by"),
            expires=_dt_from_str(constraints_data.get("expires")),
            evidence_required=constraints_data.get("evidence_required", True),
            risk_level=RiskLevel(constraints_data["risk_level"])
            if constraints_data.get("risk_level")
            else None,
            authority_id=constraints_data.get("authority_id"),
            mandate_id=constraints_data.get("mandate_id"),
            enterprise_system_id=constraints_data.get("enterprise_system_id"),
        ),
        metadata=Metadata(
            owner=metadata_data.get("owner"),
            created_by=metadata_data.get("created_by"),
            tags=tuple(metadata_data.get("tags", [])),
            source_type=metadata_data.get("source_type"),
            source_corpus_id=metadata_data.get("source_corpus_id"),
            source_graph_approval_id=metadata_data.get("source_graph_approval_id"),
            source_graph_version=metadata_data.get("source_graph_version"),
            source_candidate_id=metadata_data.get("source_candidate_id"),
        ),
        audit=(
            AuditTrail(
                created=_dt_from_str(audit_data["created"]),
                modified=_dt_from_str(audit_data.get("modified")),
                approved=_dt_from_str(audit_data.get("approved")),
                deployed=_dt_from_str(audit_data.get("deployed")),
                modified_by=audit_data.get("modified_by"),
                approved_by=audit_data.get("approved_by"),
                deployed_by=audit_data.get("deployed_by"),
            )
            if audit_data is not None
            else None
        ),
    )


def canonical_json(policy: RuntimePolicy) -> bytes:
    return json.dumps(to_dict(policy), sort_keys=True, separators=(",", ":")).encode("utf-8")


JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RuntimePolicy",
    "type": "object",
    "required": ["id", "name", "version", "status", "scope", "conditions", "effect"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": ["string", "null"]},
        "version": {"type": "integer", "minimum": 1},
        "status": {
            "type": "string",
            "enum": [s.value for s in PolicyStatus],
        },
        "scope": {
            "type": "object",
            "required": ["principal", "action"],
            "properties": {
                "principal": {"type": "string"},
                "action": {"type": "string"},
                "agent": {"type": ["string", "null"]},
                "resource": {"type": ["string", "null"]},
            },
        },
        "conditions": {
            "type": "object",
            "required": ["all"],
            "properties": {
                "all": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "operator", "value"],
                        "properties": {
                            "field": {"type": "string"},
                            "operator": {"type": "string", "enum": [o.value for o in Operator]},
                            "value": {},
                        },
                    },
                }
            },
        },
        "effect": {"type": "string", "enum": [e.value for e in Effect]},
        "constraints": {
            "type": "object",
            "properties": {
                "delegated_by": {"type": ["string", "null"]},
                "expires": {"type": ["string", "null"], "format": "date-time"},
                "evidence_required": {"type": "boolean"},
                "risk_level": {
                    "type": ["string", "null"],
                    "enum": [r.value for r in RiskLevel] + [None],
                },
                "authority_id": {"type": ["string", "null"]},
                "mandate_id": {"type": ["string", "null"]},
                "enterprise_system_id": {"type": ["string", "null"]},
            },
        },
        "metadata": {
            "type": "object",
            "properties": {
                "owner": {"type": ["string", "null"]},
                "created_by": {"type": ["string", "null"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source_type": {"type": ["string", "null"]},
                "source_corpus_id": {"type": ["string", "null"]},
                "source_graph_approval_id": {"type": ["string", "null"]},
                "source_graph_version": {"type": ["integer", "null"]},
                "source_candidate_id": {"type": ["string", "null"]},
            },
        },
        "audit": {
            "type": ["object", "null"],
            "properties": {
                "created": {"type": "string", "format": "date-time"},
                "modified": {"type": ["string", "null"], "format": "date-time"},
                "approved": {"type": ["string", "null"], "format": "date-time"},
                "deployed": {"type": ["string", "null"], "format": "date-time"},
                "modified_by": {"type": ["string", "null"]},
                "approved_by": {"type": ["string", "null"]},
                "deployed_by": {"type": ["string", "null"]},
            },
        },
    },
}
