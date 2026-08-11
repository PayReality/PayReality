"""The system prompt, tool schema, and result-parsing logic shared by
every AuthorityGraphExtractionProvider that calls a real LLM
(ClaudeAuthorityGraphExtractionProvider, AzureFoundryAuthorityGraphExtractionProvider).

Extracted unchanged from domain/ai_authority_builder/claude_provider.py
(Authority Intelligence Program, Phase 1) specifically so a second,
Foundry-backed provider does not duplicate ~250 lines of prompt/schema/
parsing logic that must stay identical across both -- a provider's job
should be exactly "call the model," never "decide what to ask it or how
to read the answer," so that guarantee (never a Rego field, never a
deploy/activate instruction, anywhere in this schema) is enforced once,
not twice.
"""

from app.domain.ai_authority_builder.provider import (
    AuthorityGraph,
    CandidateConflict,
    CandidateGap,
    CandidateOperation,
    CandidatePrincipal,
    CandidateQuestion,
    CandidateRelationship,
    CandidateResource,
)
from app.domain.ai_policy_builder.provider import CandidateCondition, CandidateRuntimePolicy
from app.domain.compiler_v2.compiler_v2 import FINANCIAL_VOCABULARY
from app.domain.runtime_policy.conditions import Operator

TOOL_NAME = "record_authority_graph"

SYSTEM_PROMPT_TEMPLATE = """You reconstruct an organisation's authority structure from a corpus of one or
more governance documents (delegation-of-authority memos, approval
matrices, procurement/HR/risk policies, governance frameworks, security
policies, standard operating procedures, contracts). Treat every document
in the corpus as one body of evidence about the same organisation; do not
analyse them in isolation. A limit stated in one document and contradicted
in another is exactly the kind of thing you must notice and report as a
conflict, not silently pick one and discard the other.

Continue extracting until you believe you have found everything the
corpus actually supports. Extract, across the whole corpus:

- Runtime Policies: every enforceable rule (who may do what, under what
  conditions, with what effect).
- Principals: every named authority holder or role, with who they report
  to if the corpus states or clearly implies it.
- Resources: every business object authority is exercised over.
- Operations: every verb (approve, reject, release, and so on) applied to
  a Resource.
- Relationships: delegation, escalation, or inheritance links between
  named Principals.
- Conflicts: contradictory or duplicate authority you notice across the
  corpus (the same principal with two different limits for the same
  resource, two principals both claiming exclusive authority, and so on).
- Gaps: information you expected to find and could not (an approver
  named but never given a limit, a resource mentioned but never scoped,
  an escalation path referenced but not defined).
- Questions: clarification questions a human reviewer should answer
  before this corpus's findings are trusted.

Extract only what the text actually supports. If a field is not clearly
stated, leave it null and name it in missing_fields (for Runtime Policies)
rather than guessing. Cite the exact source_excerpt and source_location
(the location marker from the document text, prefixed with which file it
came from) for every finding except Conflicts (which relate multiple
findings to each other, not one passage) and Questions (which are
requests for information, not claims about the text).

You produce structured fields only. You never produce Rego, source code,
or any other executable policy language, and you never suggest or imply
that anything should be deployed or activated; that does not exist in
your output schema.

Known actions for Runtime Policies: {known_actions}. Use the closest
match; do not invent a new action name."""


def build_system_prompt() -> str:
    known_actions = sorted(FINANCIAL_VOCABULARY.known_actions)
    return SYSTEM_PROMPT_TEMPLATE.format(known_actions=", ".join(known_actions))


def build_tool_schema() -> dict:
    known_actions = sorted(FINANCIAL_VOCABULARY.known_actions)
    known_operators = [o.value for o in Operator]

    cited = {
        "source_excerpt": {"type": "string", "description": "The exact sentence(s) or row this finding was extracted from."},
        "source_location": {
            "type": "string",
            "description": "Which file and location, e.g. \"FILE: doa_memo.pdf, page 4\".",
        },
    }
    confidence_field = {
        "confidence": {"type": "number", "description": "Your own honest confidence, 0.0 to 1.0."}
    }

    policy_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "principal": {"type": "string"},
            "action": {"type": "string", "description": f"One of: {', '.join(known_actions)}. Use the closest match; do not invent new values."},
            "resource": {"type": ["string", "null"]},
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {"type": "string", "enum": known_operators},
                        "value": {},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "delegated_by": {"type": ["string", "null"]},
                    "evidence_required": {"type": ["boolean", "null"]},
                    "risk_level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                },
            },
            "effect": {"type": "string", "enum": ["allow", "deny", "require_human_review"]},
            "metadata_owner": {"type": ["string", "null"]},
            "metadata_tags": {"type": "array", "items": {"type": "string"}},
            **confidence_field,
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            **cited,
        },
        "required": ["name", "principal", "action", "effect", "confidence", "source_excerpt", "source_location"],
    }

    principal_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": ["string", "null"]},
            "reports_to": {"type": ["string", "null"], "description": "Name of this principal's manager/superior, if stated or clearly implied."},
            **confidence_field,
            **cited,
        },
        "required": ["name", "confidence", "source_excerpt", "source_location"],
    }

    resource_or_operation_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": ["string", "null"]},
            **confidence_field,
            **cited,
        },
        "required": ["name", "confidence", "source_excerpt", "source_location"],
    }

    relationship_item = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["delegation", "escalation", "inheritance"]},
            "from_principal": {"type": "string"},
            "to_principal": {"type": "string"},
            "description": {"type": ["string", "null"]},
            **confidence_field,
            **cited,
        },
        "required": ["kind", "from_principal", "to_principal", "confidence", "source_excerpt", "source_location"],
    }

    conflict_item = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "reasoning": {"type": ["string", "null"]},
            **confidence_field,
        },
        "required": ["description", "confidence"],
    }

    gap_item = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            **confidence_field,
            "source_excerpt": {"type": ["string", "null"]},
            "source_location": {"type": ["string", "null"]},
        },
        "required": ["description", "confidence"],
    }

    question_item = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "context": {"type": ["string", "null"]},
        },
        "required": ["question"],
    }

    return {
        "type": "object",
        "properties": {
            "policies": {"type": "array", "items": policy_item},
            "principals": {"type": "array", "items": principal_item},
            "resources": {"type": "array", "items": resource_or_operation_item},
            "operations": {"type": "array", "items": resource_or_operation_item},
            "relationships": {"type": "array", "items": relationship_item},
            "conflicts": {"type": "array", "items": conflict_item},
            "gaps": {"type": "array", "items": gap_item},
            "questions": {"type": "array", "items": question_item},
        },
        "required": ["policies", "principals", "resources", "operations", "relationships", "conflicts", "gaps", "questions"],
    }


def parse_graph_input(graph_input: dict) -> AuthorityGraph:
    """The one, shared dict -> AuthorityGraph mapping. Deterministic and
    provider-independent: given the same structured dict, every provider
    produces the identical AuthorityGraph, regardless of which model or
    vendor produced that dict."""
    policies = tuple(
        CandidateRuntimePolicy(
            name=p["name"],
            principal=p["principal"],
            action=p["action"],
            effect=p["effect"],
            confidence=max(0.0, min(1.0, float(p["confidence"]))),
            source_excerpt=p["source_excerpt"],
            source_location=p["source_location"],
            resource=p.get("resource"),
            conditions=tuple(
                CandidateCondition(field=c["field"], operator=c["operator"], value=c["value"])
                for c in p.get("conditions", [])
            ),
            delegated_by=(p.get("constraints") or {}).get("delegated_by"),
            evidence_required=(p.get("constraints") or {}).get("evidence_required"),
            risk_level=(p.get("constraints") or {}).get("risk_level"),
            metadata_owner=p.get("metadata_owner"),
            metadata_tags=tuple(p.get("metadata_tags", [])),
            missing_fields=tuple(p.get("missing_fields", [])),
        )
        for p in graph_input.get("policies", [])
    )

    principals = tuple(
        CandidatePrincipal(
            name=p["name"],
            confidence=max(0.0, min(1.0, float(p["confidence"]))),
            source_excerpt=p["source_excerpt"],
            source_location=p["source_location"],
            role=p.get("role"),
            reports_to=p.get("reports_to"),
        )
        for p in graph_input.get("principals", [])
    )

    resources = tuple(
        CandidateResource(
            name=r["name"],
            confidence=max(0.0, min(1.0, float(r["confidence"]))),
            source_excerpt=r["source_excerpt"],
            source_location=r["source_location"],
            description=r.get("description"),
        )
        for r in graph_input.get("resources", [])
    )

    operations = tuple(
        CandidateOperation(
            name=o["name"],
            confidence=max(0.0, min(1.0, float(o["confidence"]))),
            source_excerpt=o["source_excerpt"],
            source_location=o["source_location"],
            description=o.get("description"),
        )
        for o in graph_input.get("operations", [])
    )

    relationships = tuple(
        CandidateRelationship(
            kind=r["kind"],
            from_principal=r["from_principal"],
            to_principal=r["to_principal"],
            confidence=max(0.0, min(1.0, float(r["confidence"]))),
            source_excerpt=r["source_excerpt"],
            source_location=r["source_location"],
            description=r.get("description"),
        )
        for r in graph_input.get("relationships", [])
    )

    conflicts = tuple(
        CandidateConflict(
            description=c["description"],
            confidence=max(0.0, min(1.0, float(c["confidence"]))),
            reasoning=c.get("reasoning"),
        )
        for c in graph_input.get("conflicts", [])
    )

    gaps = tuple(
        CandidateGap(
            description=g["description"],
            confidence=max(0.0, min(1.0, float(g["confidence"]))),
            source_excerpt=g.get("source_excerpt"),
            source_location=g.get("source_location"),
        )
        for g in graph_input.get("gaps", [])
    )

    questions = tuple(
        CandidateQuestion(question=q["question"], context=q.get("context"))
        for q in graph_input.get("questions", [])
    )

    return AuthorityGraph(
        policies=policies,
        principals=principals,
        resources=resources,
        operations=operations,
        relationships=relationships,
        conflicts=conflicts,
        gaps=gaps,
        questions=questions,
    )
