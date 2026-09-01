"""Product Experience V3.2, Part C ("Draft with AI"): the JSON schema and
system prompt for turning one natural-language instruction (plus,
optionally, the rule currently open in the manual builder) into ONE
proposed RuntimePolicy, expressed as the exact same CandidateRuntimePolicy
shape the AI Policy Builder's own document-extraction pipeline already
produces (domain/ai_policy_builder/provider.py) -- reused directly, not
duplicated, so a proposal from either pipeline converts through the
existing, already-tested candidate_to_content().

This is deliberately a close sibling of extraction_shared.py, not a
generalization of it: extraction reads a whole document and returns many
candidates; this reads one instruction (in the context of a draft already
open in the builder, for edit/explain) and returns at most one proposal,
plus an explicit signal when the instruction is too ambiguous to propose
anything (section 36) -- a shape extraction_shared.py's own schema has no
reason to carry, since a document either yields well-formed candidates or
none at all.
"""

from app.domain.ai_policy_builder.provider import CandidateCondition, CandidateRuntimePolicy
from app.domain.compiler_v2.compiler_v2 import GENERIC_VOCABULARY
from app.domain.runtime_policy.conditions import Operator

TOOL_NAME = "record_policy_draft_proposal"

SYSTEM_PROMPT_TEMPLATE = """You help a human express an organisation's own delegated authority as a
Runtime Policy for PayReality. You NEVER create, approve, or activate
organisational authority yourself -- you only propose structured fields a
human then explicitly reviews and applies. If the instruction already
implies authority you have not been told the organisation actually holds
(a specific person's real limit, a real approval chain, a real risk
classification), do not invent it: propose only what the instruction
itself states, and name anything you could not confidently determine in
missing_fields.

If the instruction is genuinely ambiguous about who ("senior people"),
what counts as a threshold ("large transactions"), which action, or which
resource/system, do NOT guess a specific value. Instead, set
clarifying_question to one short, specific question that would resolve the
ambiguity, and leave proposal null. Never invent enterprise authority to
avoid asking a clarifying question.

If the instruction plainly requires more than one Runtime Policy to
represent correctly (Runtime Policies are flat, single-stage, AND-only
rules -- there is no multi-step or sequential-approval concept), propose
the single Policy you can express confidently and set
requires_additional_policies to true with a short note explaining what the
remaining part would need, rather than distorting one Policy to
approximate something it cannot represent.

Known actions: {known_actions}. Use the closest match; do not invent a new
action name -- if nothing is close, leave action null and name it in
missing_fields instead of forcing a mismatch.

You produce structured fields only: a name, a principal, an action, an
optional resource, an optional agent restriction, a list of conditions,
constraints, an effect, and metadata. You never produce Rego, source code,
or any other executable policy language.

Effect must be exactly one of: allow, deny, require_human_review. Prefer
require_human_review whenever the instruction describes an approval,
escalation, or review step rather than an unconditional grant or refusal."""


def build_system_prompt() -> str:
    known_actions = sorted(GENERIC_VOCABULARY.known_actions)
    return SYSTEM_PROMPT_TEMPLATE.format(known_actions=", ".join(known_actions))


def build_tool_schema() -> dict:
    known_actions = sorted(GENERIC_VOCABULARY.known_actions)
    known_operators = [o.value for o in Operator]
    proposal_schema = {
        "type": ["object", "null"],
        "properties": {
            "name": {"type": "string"},
            "principal": {"type": "string"},
            "action": {
                "type": "string",
                "description": f"One of: {', '.join(known_actions)}. Use the closest match; do not invent new values.",
            },
            "resource": {"type": ["string", "null"]},
            "agent": {
                "type": ["string", "null"],
                "description": "Restricts this policy to one specific autonomous Agent, if the instruction names one. Null means any agent for this principal.",
            },
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {"type": "string", "enum": known_operators},
                        "value": {"description": "A number, string, boolean, or list, matching the operator."},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "delegated_by": {"type": ["string", "null"]},
                    "evidence_required": {"type": ["boolean", "null"]},
                    "risk_level": {"type": ["string", "null"], "enum": ["low", "medium", "high", "critical", None]},
                },
            },
            "effect": {"type": "string", "enum": ["allow", "deny", "require_human_review"]},
            "metadata_owner": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "principal", "action", "effect", "confidence"],
    }

    return {
        "type": "object",
        "properties": {
            "proposal": proposal_schema,
            "clarifying_question": {
                "type": ["string", "null"],
                "description": "Set (and leave proposal null) when the instruction is too ambiguous to propose confidently.",
            },
            "requires_additional_policies": {"type": "boolean"},
            "additional_policies_note": {"type": ["string", "null"]},
        },
        "required": ["proposal", "clarifying_question", "requires_additional_policies"],
    }


class PolicyDraftResult:
    """The parsed, structured result of one Draft/Edit call -- never the
    raw model dict (section 47: the model's own output is untrusted until
    parsed against this exact shape and, separately, validated against
    real organisation entities by policy_drafting_service.py)."""

    def __init__(
        self,
        proposal: CandidateRuntimePolicy | None,
        proposal_agent: str | None,
        clarifying_question: str | None,
        requires_additional_policies: bool,
        additional_policies_note: str | None,
    ):
        self.proposal = proposal
        # CandidateRuntimePolicy (ai_policy_builder/provider.py) has no
        # `agent` field -- it was designed for document extraction, where
        # a document virtually never names a specific Agent id. Kept
        # alongside the proposal here rather than added to that shared
        # dataclass, so this module's own agent-restriction feature never
        # changes the meaning of a field the document-extraction pipeline
        # already depends on.
        self.proposal_agent = proposal_agent
        self.clarifying_question = clarifying_question
        self.requires_additional_policies = requires_additional_policies
        self.additional_policies_note = additional_policies_note


def parse_draft_result(data: dict) -> PolicyDraftResult:
    raw_proposal = data.get("proposal")
    proposal: CandidateRuntimePolicy | None = None
    if raw_proposal is not None:
        constraints = raw_proposal.get("constraints") or {}
        proposal = CandidateRuntimePolicy(
            name=raw_proposal["name"],
            principal=raw_proposal["principal"],
            action=raw_proposal["action"],
            effect=raw_proposal["effect"],
            confidence=max(0.0, min(1.0, float(raw_proposal["confidence"]))),
            source_excerpt="",
            source_location="conversational draft",
            resource=raw_proposal.get("resource"),
            conditions=tuple(
                CandidateCondition(field=c["field"], operator=c["operator"], value=c["value"])
                for c in raw_proposal.get("conditions", [])
            ),
            delegated_by=constraints.get("delegated_by"),
            evidence_required=constraints.get("evidence_required"),
            risk_level=constraints.get("risk_level"),
            metadata_owner=raw_proposal.get("metadata_owner"),
            missing_fields=tuple(raw_proposal.get("missing_fields", [])),
        )
    return PolicyDraftResult(
        proposal=proposal,
        proposal_agent=(raw_proposal or {}).get("agent"),
        clarifying_question=data.get("clarifying_question"),
        requires_additional_policies=bool(data.get("requires_additional_policies", False)),
        additional_policies_note=data.get("additional_policies_note"),
    )
