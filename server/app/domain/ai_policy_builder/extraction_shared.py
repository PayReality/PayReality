"""The system prompt, tool schema, and result-parsing logic shared by
every RuntimePolicyExtractionProvider that calls a real LLM
(ClaudeRuntimePolicyExtractionProvider, AzureFoundryRuntimePolicyExtractionProvider).

Extracted from domain/ai_policy_builder/claude_provider.py (Milestone 6,
AI_PIPELINE_CONSOLIDATION_REVIEW.md), mirroring the exact same
extraction already done for domain/ai_authority_builder's own two
providers (extraction_shared.py there) and for the identical reason: a
second, Foundry-backed provider must ask for and parse the identical
CandidateRuntimePolicy shape the Claude provider already does, and that
guarantee belongs in one place, not two independently-maintained copies.

PROMPT_LIBRARY.md is the source of truth for the exact prompt and schema
this sends; keep the two in sync. Forced tool-use is what makes "the AI
must never generate Rego" a structural property of the call, not a
hoped-for prompt outcome.
"""

from app.domain.ai_policy_builder.provider import CandidateCondition, CandidateRuntimePolicy
from app.domain.compiler_v2.compiler_v2 import FINANCIAL_VOCABULARY
from app.domain.runtime_policy.conditions import Operator

TOOL_NAME = "record_candidate_runtime_policies"

SYSTEM_PROMPT_TEMPLATE = """You extract candidate Runtime Policies from enterprise authority documents
(delegation-of-authority memos, signing-authority schedules, board
resolutions, policy summaries). A Runtime Policy states who may do what,
under what conditions, and with what effect.

Extract only what the text actually supports. If a field is not clearly
stated, leave it null (or an empty list, for conditions/tags) and name that
field in missing_fields rather than guessing or inferring a plausible-
sounding default.

A single document commonly grants authority to multiple people or roles;
extract one candidate per distinct grant, not one candidate for the whole
document. Do not merge two different principals' limits into one candidate
even if they appear in the same paragraph or table row.

You produce structured fields only: a name, a principal, an action, an
optional resource, a list of conditions, constraints, an effect, and
metadata. You never produce Rego, source code, or any other executable
policy language; that does not exist in your output schema, and you should
not attempt to describe or approximate it in any field, including free-text
ones.

For every candidate, report your own honest confidence (0.0 to 1.0) that
this candidate is fully and correctly extracted, and list every field you
were not confident about in missing_fields, even if you filled in a
best-guess value for it. Cite the exact source_excerpt (the sentence(s) or
row this candidate came from) and source_location (the location marker
from the document text, e.g. "page 4" or "sheet 'Vendors', row 12") for
every candidate; never fabricate a citation.

Known actions: {known_actions}. Use the closest match; do not invent a new
action name. If nothing in the document is close to any known action, omit
that candidate entirely rather than forcing a mismatch."""


def build_system_prompt() -> str:
    known_actions = sorted(FINANCIAL_VOCABULARY.known_actions)
    return SYSTEM_PROMPT_TEMPLATE.format(known_actions=", ".join(known_actions))


def build_tool_schema() -> dict:
    """The raw JSON schema only, no vendor-specific tool-envelope fields
    (name/description) -- Claude's provider wraps this itself in its own
    "input_schema" field; the Foundry provider passes it as-is to
    generate_structured's json_schema parameter. Matches
    domain/ai_authority_builder/extraction_shared.py's identical split."""
    known_actions = sorted(FINANCIAL_VOCABULARY.known_actions)
    known_operators = [o.value for o in Operator]
    candidate_item = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A short, human-readable name for this policy, e.g. 'Regional Controller EMEA - Vendor Payment Limit'.",
            },
            "principal": {
                "type": "string",
                "description": "The role or named individual this grant is for, e.g. 'Regional Controller, EMEA'.",
            },
            "action": {
                "type": "string",
                "description": f"One of: {', '.join(known_actions)}. Use the closest match; do not invent new values.",
            },
            "resource": {
                "type": ["string", "null"],
                "description": "What the action targets, if the document names one specifically. Null if unscoped.",
            },
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "e.g. 'amount', 'currency'."},
                        "operator": {"type": "string", "enum": known_operators},
                        "value": {"description": "A number, string, boolean, or list, matching the operator."},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "delegated_by": {"type": ["string", "null"], "description": "Who granted this authority, if named."},
                    "evidence_required": {"type": ["boolean", "null"]},
                    "risk_level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                },
            },
            "effect": {
                "type": "string",
                "enum": ["allow", "deny", "require_human_review"],
                "description": "What happens when this policy's conditions are met. Use require_human_review if the document describes an approval or escalation step.",
            },
            "metadata_owner": {
                "type": ["string", "null"],
                "description": "Who is accountable for this policy (e.g. the approving executive), if named.",
            },
            "metadata_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short free-text labels, e.g. a department or document section name.",
            },
            "confidence": {
                "type": "number",
                "description": "Your own honest confidence, 0.0 to 1.0, that this candidate is fully and correctly extracted.",
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Names of fields above you could not confidently determine from the text.",
            },
            "source_excerpt": {
                "type": "string",
                "description": "The exact sentence(s) or row this candidate was extracted from.",
            },
            "source_location": {
                "type": "string",
                "description": "The location marker from the document text this candidate came from.",
            },
        },
        "required": ["name", "principal", "action", "effect", "confidence", "source_excerpt", "source_location"],
    }

    return {
        "type": "object",
        "properties": {
            "candidates": {"type": "array", "items": candidate_item},
        },
        "required": ["candidates"],
    }


def parse_candidates_input(data: dict) -> list[CandidateRuntimePolicy]:
    """The one, shared dict -> CandidateRuntimePolicy list mapping.
    Deterministic and provider-independent: given the same structured
    dict, every provider produces identical candidates, regardless of
    which model or vendor produced that dict."""
    candidates: list[CandidateRuntimePolicy] = []
    for raw in data.get("candidates", []):
        constraints = raw.get("constraints") or {}
        candidates.append(
            CandidateRuntimePolicy(
                name=raw["name"],
                principal=raw["principal"],
                action=raw["action"],
                effect=raw["effect"],
                confidence=max(0.0, min(1.0, float(raw["confidence"]))),
                source_excerpt=raw["source_excerpt"],
                source_location=raw["source_location"],
                resource=raw.get("resource"),
                conditions=tuple(
                    CandidateCondition(field=c["field"], operator=c["operator"], value=c["value"])
                    for c in raw.get("conditions", [])
                ),
                delegated_by=constraints.get("delegated_by"),
                evidence_required=constraints.get("evidence_required"),
                risk_level=constraints.get("risk_level"),
                metadata_owner=raw.get("metadata_owner"),
                metadata_tags=tuple(raw.get("metadata_tags", [])),
                missing_fields=tuple(raw.get("missing_fields", [])),
            )
        )
    return candidates
