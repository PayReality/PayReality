"""The system prompt, tool schema, response-rendering, and strict
response validation shared by every DiscoveryProvider that calls a real
LLM (today: ClaudeDiscoveryProvider). Mirrors domain/ai_policy_builder/
extraction_shared.py's own split exactly: the prompt/schema/parsing logic
lives in one place so a future second LLM-backed provider (e.g. an Azure
AI Foundry one, not built in this pass -- see the module's own README)
is guaranteed to ask for and interpret the identical candidate shape.

Unlike the sibling extraction_shared.py modules, this one additionally
defines a STRICT Pydantic response schema (`DiscoveryResponseModel`) and
validates every model response against it, per this feature's own brief:
"define a strict Pydantic response schema and validate the model's output
against it -- reject/retry on a malformed response rather than trusting
free text." Neither sibling AI feature does this (their forced tool-use
JSON schema is trusted as-is); this is a deliberate, disclosed
enhancement specific to this feature, not a divergence from an existing
convention that was ignored.

Validation here checks two independent things, either of which raises
`MalformedDiscoveryResponseError` (caught by claude_provider.py's bounded
retry loop):
1. Structural shape via `DiscoveryResponseModel.model_validate` (field
   types/presence/enum membership, including that `confidence` is one of
   low/medium/high and that a pattern's `supporting_case_ids` is never
   empty -- an unsupported assertion is not better than no suggestion).
2. Every `supporting_case_ids` entry (pattern or question) actually
   refers to a real case id from THIS discovery run's own input set --
   never trusted at face value. A model citing a case id it was never
   given is treated as a malformed response, not a valid-but-wrong one,
   since a fabricated citation defeats the entire point of grounding a
   suggestion in real case evidence."""

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.domain.decision_intelligence.ai_discovery.provider import (
    CandidatePattern,
    CandidateQuestion,
    CaseForDiscovery,
    DiscoveryResult,
)

TOOL_NAME = "record_candidate_discovery_patterns"

SYSTEM_PROMPT = """You analyze a bounded set of real historical decision cases from one business
workflow, each with its recorded facts, escalation_reason (if any), the
human_decision actually made, its outcome, and status.

Your job is to propose candidate PATTERNS: recurring uncertainty across two
or more of these cases (e.g. cases with near-identical facts but different
human decisions, a fact that's recorded on some cases and missing on
others, or several cases escalated for closely related reasons). For each
pattern, propose zero or more candidate QUESTIONS whose answer would
resolve that specific uncertainty for every future case like it.

Hard rules:
- Every pattern's supporting_case_ids must list at least one real case_id
  from the cases you were given. NEVER invent a case_id, and never cite one
  that wasn't in your input. A pattern with no real supporting case is not
  a valid pattern.
- Ground every rationale in the actual facts/escalation_reasons/outcomes
  you observed on the cited cases -- cite what you actually saw, not a
  generic justification.
- Report your own honest confidence (low/medium/high) for each pattern,
  reflecting how directly the evidence supports it (e.g. two cases with
  genuinely near-identical facts but opposite decisions is strong,
  direct evidence and should be "high"; a loose thematic similarity is
  weaker and should be "low"). This is your own heuristic judgement, not
  a calibrated statistical score -- never overstate it.
- A question is a request for information, not a claim to be confident or
  unconfident about -- do not include a confidence field on a question.
- Never describe a pattern or question as "confirmed," "established," or
  otherwise settled. Every one of these is a hypothesis for a human
  reviewer to accept or dismiss, never a conclusion you have reached on
  the organisation's behalf.
- If you find no genuine recurring pattern in the given cases, return an
  empty patterns list. An empty, honest result is correct and expected
  when the cases don't actually show a recurring issue -- never force a
  pattern to avoid returning nothing."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def format_cases_for_prompt(cases: list[CaseForDiscovery]) -> str:
    """The only data sent to the model: exactly the five fields this
    feature's brief named as discovery's input (plus each case's own id,
    so a suggestion can cite it), never the organization_id,
    created_by_user_id, external_ref, evidence_refs, ai_recommendation, or
    outcome_evidence also present on a real DICase row -- the same
    data-minimization posture already implicit in what
    CaseForDiscovery.provider.py's dataclass carries in the first place
    (see that module's own docstring)."""
    rendered = [
        {
            "case_id": c.id,
            "facts": c.facts,
            "escalation_reason": c.escalation_reason,
            "human_decision": c.human_decision,
            "outcome": c.outcome,
            "status": c.status,
        }
        for c in cases
    ]
    return json.dumps(rendered, indent=2, default=str)


def build_tool_schema() -> dict:
    question_item = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short, specific candidate question."},
            "description": {
                "type": "string",
                "description": "What answering this question would resolve, in plain business language.",
            },
            "rationale": {
                "type": "string",
                "description": "Why you propose this question, citing the actual facts/escalation_reasons/outcomes you saw.",
            },
            "supporting_case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Real case_id values (from your input) this question is specifically grounded in, if any beyond its parent pattern's own.",
            },
        },
        "required": ["title", "description", "rationale"],
    }
    pattern_item = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short, specific name for this candidate pattern."},
            "description": {
                "type": "string",
                "description": "What recurring uncertainty this pattern names, in plain business language.",
            },
            "rationale": {
                "type": "string",
                "description": "Why you propose this pattern, citing the actual facts/escalation_reasons/outcomes you saw on the cited cases.",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Your own honest, heuristic judgement of how directly the evidence supports this pattern.",
            },
            "supporting_case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Real case_id values (from your input) this pattern is grounded in. Never empty, never invented.",
            },
            "questions": {
                "type": "array",
                "items": question_item,
                "description": "Candidate questions whose answer would resolve this specific pattern.",
            },
        },
        "required": ["title", "description", "rationale", "confidence", "supporting_case_ids"],
    }
    return {
        "type": "object",
        "properties": {
            "patterns": {"type": "array", "items": pattern_item},
        },
        "required": ["patterns"],
    }


class _SuggestedQuestionModel(BaseModel):
    title: str
    description: str
    rationale: str
    supporting_case_ids: list[str] = Field(default_factory=list)


class _SuggestedPatternModel(BaseModel):
    title: str
    description: str
    rationale: str
    confidence: Literal["low", "medium", "high"]
    supporting_case_ids: list[str] = Field(min_length=1)
    questions: list[_SuggestedQuestionModel] = Field(default_factory=list)


class DiscoveryResponseModel(BaseModel):
    """The strict response schema the brief requires -- validated
    against every real model response before anything from it is ever
    trusted or converted into a CandidatePattern/CandidateQuestion."""

    patterns: list[_SuggestedPatternModel] = Field(default_factory=list)


class MalformedDiscoveryResponseError(Exception):
    pass


def parse_discovery_response(data: dict, valid_case_ids: set[str]) -> DiscoveryResult:
    try:
        parsed = DiscoveryResponseModel.model_validate(data)
    except ValidationError as e:
        raise MalformedDiscoveryResponseError(f"response failed schema validation: {e}") from e

    patterns: list[CandidatePattern] = []
    for p in parsed.patterns:
        unknown = [cid for cid in p.supporting_case_ids if cid not in valid_case_ids]
        if unknown:
            raise MalformedDiscoveryResponseError(
                f"pattern '{p.title}' cites case id(s) not present in the supplied case set: {unknown}"
            )
        questions: list[CandidateQuestion] = []
        for q in p.questions:
            unknown_q = [cid for cid in q.supporting_case_ids if cid not in valid_case_ids]
            if unknown_q:
                raise MalformedDiscoveryResponseError(
                    f"question '{q.title}' cites case id(s) not present in the supplied case set: {unknown_q}"
                )
            questions.append(
                CandidateQuestion(
                    title=q.title,
                    description=q.description,
                    rationale=q.rationale,
                    supporting_case_ids=tuple(q.supporting_case_ids),
                )
            )
        patterns.append(
            CandidatePattern(
                title=p.title,
                description=p.description,
                rationale=p.rationale,
                confidence=p.confidence,
                supporting_case_ids=tuple(p.supporting_case_ids),
                questions=tuple(questions),
            )
        )
    return DiscoveryResult(patterns=tuple(patterns))
