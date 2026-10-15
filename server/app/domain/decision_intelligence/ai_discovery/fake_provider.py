"""Deterministic FakeDiscoveryProvider: the AI discovery feature's no-API-
key, zero-external-call, zero-cost fallback, the path every deployment
without ANTHROPIC_API_KEY (or Azure AI Foundry) configured actually runs
in production, not a throwaway stub. Unlike the sibling fake providers
(domain/ai_policy_builder/fake_provider.py, domain/ai_authority_builder/
fake_provider.py), which return a single hardcoded, document-shaped
example because their real input is unstructured document text, this
feature's input is real, structured DICase rows, so this fake provider
can and does run genuine, deterministic analysis over the actual data it's
given, not a canned response. It is the single most-tested code path in
this feature: most organisations will run on this provider, possibly
forever.

Three independent heuristics, each producing zero or more
CandidatePattern rows (each carrying zero or more CandidateQuestion rows
of its own):

1. `_conflicting_outcome_patterns`: groups of two or more cases whose
   recorded facts are identical except for at most one field, but whose
   recorded human_decision differs. This is a genuine, concrete,
   structural observation, not a correlation or a guess, but it has no
   single necessary cause. It could reflect an omitted fact, different
   policy versions or dates, a legitimate exception, an incorrect
   historical decision, a data or recording error, genuine unresolved
   ambiguity, or another explanation not yet known. The pattern and its
   question surface the observation and ask what explains it; neither
   may assert the cause. Confidence "high" describes how precisely the
   facts match, never certainty about why the decisions differ.
2. `_missing_field_patterns`: a fact key that's present (non-null) on at
   least one case in this batch but absent (missing or null) on at least
   two others. This only means the field is sometimes recorded and
   sometimes not; it is not evidence that the field is required, or even
   relevant, to the decision. Confidence: "medium" (a real, precise
   signal about the data, never a claim about what the data means).
3. `_escalation_reason_patterns`: clusters cases whose escalation_reason
   text shares at least 50% of its significant words (a simple, bounded,
   deterministic Jaccard-similarity union-find clustering, no ML, no
   external call). The fuzziest of the three heuristics, since free text
   similarity is an approximation, not an exact match. Confidence: "low".

Every group below requires at least MIN_GROUP_SIZE (2) supporting cases:
a single case is an observation, not a recurring pattern."""

import itertools
import json
import re
from collections import defaultdict

from app.domain.decision_intelligence.ai_discovery.provider import (
    CandidatePattern,
    CandidateQuestion,
    CaseForDiscovery,
    DiscoveryResult,
)

MIN_GROUP_SIZE = 2

_STOPWORDS = {
    "the", "a", "an", "of", "to", "is", "was", "were", "for", "in", "on", "and", "or",
    "no", "not", "this", "that", "with", "by", "as", "at", "it", "be", "has", "have",
}


class _UnionFind:
    """Tiny, dependency-free union-find so both the conflicting-outcome
    and escalation-reason heuristics can merge overlapping pairwise
    matches into connected groups without pulling in a graph library for
    something this small."""

    def __init__(self, n: int):
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[ry] = rx

    def groups(self, n: int) -> list[list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            out[self.find(i)].append(i)
        return list(out.values())


def _facts_near_identical(a: dict, b: dict, max_differences: int = 1) -> tuple[bool, list[str]]:
    """True (plus the differing field names) when `a` and `b` disagree on
    at most `max_differences` keys, considering every key present on
    either side. Two cases with completely disjoint fact schemas will
    correctly never match: every key either side has but the other
    doesn't also counts as a difference."""
    keys = set(a) | set(b)
    differing = sorted(k for k in keys if a.get(k) != b.get(k))
    return len(differing) <= max_differences, differing


def _conflicting_outcome_patterns(cases: list[CaseForDiscovery]) -> list[CandidatePattern]:
    decided = [c for c in cases if c.human_decision]
    uf = _UnionFind(len(decided))
    differing_fields_by_pair: dict[frozenset[int], list[str]] = {}

    for i, j in itertools.combinations(range(len(decided)), 2):
        near_identical, differing = _facts_near_identical(decided[i].facts, decided[j].facts)
        if not near_identical or decided[i].human_decision == decided[j].human_decision:
            continue
        uf.union(i, j)
        differing_fields_by_pair[frozenset((i, j))] = differing

    patterns: list[CandidatePattern] = []
    for members in uf.groups(len(decided)):
        member_set = set(members)
        relevant = {pair: fields for pair, fields in differing_fields_by_pair.items() if pair <= member_set}
        if len(members) < MIN_GROUP_SIZE or not relevant:
            continue

        member_cases = [decided[i] for i in members]
        case_ids = tuple(c.id for c in member_cases)
        differing_fields = sorted({f for fields in relevant.values() for f in fields})
        decisions_seen = sorted({json.dumps(c.human_decision, sort_keys=True) for c in member_cases})

        # Two distinct cases, handled explicitly rather than papering over
        # the empty-differing-fields one with a placeholder phrase: cases
        # can disagree on exactly one recorded field, or share identical
        # recorded facts outright (disclosed bug, fixed here: the previous
        # text called this second case "no recorded fields", which read as
        # nonsense rather than the real finding, matching facts in full).
        if differing_fields:
            match_clause = f"match except for {', '.join(differing_fields)}"
            title = f"Conflicting decisions on near-identical cases ({', '.join(differing_fields)})"
            question_title = (
                f"These cases have matching recorded facts except for {', '.join(differing_fields)}, "
                "but different decisions. What explains the difference?"
            )
        else:
            match_clause = "match in full"
            title = "Conflicting decisions on cases with identical recorded facts"
            question_title = "These cases have matching recorded facts but different decisions. What explains the difference?"

        rationale = (
            f"Compared every pair of cases with a recorded human_decision: cases "
            f"{', '.join(case_ids)} have facts that {match_clause}, yet their recorded decisions "
            f"disagree ({'; '.join(decisions_seen)}). This is an observation, not an explanation: it "
            "could reflect an omitted fact, different policy versions or dates, a legitimate "
            "exception, an incorrect historical decision, a data or recording error, genuine "
            "unresolved ambiguity, or another cause not yet known. Investigate before assuming which."
        )

        # Specificity is earned, not assumed: only when exactly one field
        # differs AND the group takes exactly two distinct values on it do
        # we have enough grounding to ask a specific, answerable yes/no
        # question naming the actual field and actual values. Any other
        # shape (zero differing fields, more than one, or more than two
        # values on a single field) genuinely doesn't support a narrower
        # question than the observation itself -- stays broad, per the
        # brief's own instruction not to force specificity past what the
        # data supports.
        single_field_values = None
        if len(differing_fields) == 1:
            field_name = differing_fields[0]
            distinct_values = sorted(
                {json.dumps(c.facts.get(field_name), sort_keys=True) for c in member_cases}
            )
            if len(distinct_values) == 2:
                single_field_values = (field_name, distinct_values)

        if single_field_values:
            field_name, (value_a, value_b) = single_field_values
            specific_question_title = (
                f"Does '{field_name}' ({value_a} vs {value_b}) change the decision, given every "
                "other recorded fact matches?"
            )
            candidate_explanation = (
                f"'{field_name}' may be the deciding factor between these otherwise-matching cases."
            )
        else:
            specific_question_title = question_title
            candidate_explanation = (
                "One or more of the differing/matching fields above may be the deciding factor, but "
                "no single field's values line up cleanly enough across this group to name one."
            )

        alternative_explanations = (
            "an omitted fact not captured in any recorded field",
            "the cases were governed by different policy versions or effective dates",
            "a legitimate, case-specific exception applied to one of them",
            "one of the two recorded decisions was simply incorrect",
            "a data entry, retrieval, or integration defect affected how a fact was recorded",
            "genuine unresolved ambiguity that still requires case-by-case judgement",
        )
        missing_evidence = (
            "confirmation of which policy version or effective date governed each case",
            "whether any context outside the recorded facts influenced either decision",
        ) + ((f"whether '{single_field_values[0]}' was reliably captured for both cases, "
              "rather than a retrieval or integration gap",) if single_field_values else ())
        potential_impact = (
            f"If '{single_field_values[0]}' is confirmed decisive, a rule condition on it could resolve "
            "this gap for future cases; if not, these cases should continue receiving individual "
            "judgement."
        ) if single_field_values else (
            "If a specific deciding factor is confirmed, it could become a rule condition for future "
            "cases; if the difference turns out to be case-specific, no new rule is warranted."
        )

        question = CandidateQuestion(
            title=specific_question_title,
            description=(
                f"{len(member_cases)} cases share recorded facts that {match_clause} but were "
                "decided differently. Confirming what explains the difference, and recording that as "
                "an approved answer, would clarify how to handle every future case like it."
            ),
            rationale=rationale,
            supporting_case_ids=case_ids,
            candidate_explanation=candidate_explanation,
            alternative_explanations=alternative_explanations,
            missing_evidence=missing_evidence,
            potential_impact=potential_impact,
        )
        patterns.append(
            CandidatePattern(
                title=title,
                description=(
                    f"{len(member_cases)} cases have facts that {match_clause}, but were decided "
                    f"differently: {'; '.join(decisions_seen)}. The cause is not yet known."
                ),
                rationale=rationale,
                confidence="high",
                category="other",
                supporting_case_ids=case_ids,
                questions=(question,),
                alternative_explanations=alternative_explanations,
            )
        )
    return patterns


def _missing_field_patterns(cases: list[CaseForDiscovery]) -> list[CandidatePattern]:
    all_keys: set[str] = set()
    for case in cases:
        all_keys |= {k for k, v in case.facts.items() if v is not None}

    patterns: list[CandidatePattern] = []
    for key in sorted(all_keys):
        present = [c for c in cases if c.facts.get(key) is not None]
        absent = [c for c in cases if c.facts.get(key) is None]
        if not present or len(absent) < MIN_GROUP_SIZE:
            # Either nobody records this field (not a "sometimes missing"
            # signal, just an unused key), or too few cases are missing it
            # to call it a recurring pattern.
            continue

        case_ids = tuple(c.id for c in absent)
        rationale = (
            f"Compared which cases' facts include the key '{key}': cases {', '.join(case_ids)} do "
            f"not record it at all, while {len(present)} other case(s) in this batch do. This only "
            f"shows that '{key}' is recorded inconsistently; this heuristic has no way to know "
            f"whether '{key}' is actually required, optional, or simply not applicable to the "
            "cases that lack it. Confirm relevance before treating this as a data gap."
        )
        question = CandidateQuestion(
            title=f"Is '{key}' relevant to deciding this kind of case?",
            description=(
                f"Some cases record '{key}' and others don't. This may mean it's required and "
                f"sometimes missed, or it may be a legitimately optional field that simply doesn't "
                "apply to every case. Answering this would clarify which, and what to do when it's "
                "absent."
            ),
            rationale=rationale,
            supporting_case_ids=case_ids,
            candidate_explanation=f"'{key}' may be a required input that is sometimes not recorded.",
            alternative_explanations=(
                f"'{key}' is a legitimately optional field that doesn't apply to every case",
                "a data entry or system-integration gap in how intake records this field",
                "it was considered during the original decision but simply never recorded",
            ),
            missing_evidence=(
                f"whether '{key}' is documented as mandatory in any existing policy or form",
                "whether the cases missing it genuinely had no applicable value, versus the value "
                "existing but not being captured",
            ),
            potential_impact=(
                f"If '{key}' is confirmed required, the intake process may need correcting so it's "
                f"always captured, and cases missing it may need re-review; if it's optional, no "
                "change is needed."
            ),
        )
        patterns.append(
            CandidatePattern(
                title=f"Cases missing '{key}'",
                description=(
                    f"{len(absent)} of {len(cases)} cases are missing the '{key}' fact, which is "
                    f"present on {len(present)} other case(s) in this workflow. Whether '{key}' is "
                    "actually required is not yet known; it may be a legitimately optional field."
                ),
                rationale=rationale,
                confidence="medium",
                category="missing_facts",
                supporting_case_ids=case_ids,
                questions=(question,),
            )
        )
    return patterns


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _escalation_reason_patterns(cases: list[CaseForDiscovery]) -> list[CandidatePattern]:
    escalated = [c for c in cases if c.escalation_reason and c.escalation_reason.strip()]
    tokens = [_tokenize(c.escalation_reason) for c in escalated]
    uf = _UnionFind(len(escalated))

    for i, j in itertools.combinations(range(len(escalated)), 2):
        if not tokens[i] or not tokens[j]:
            continue
        union_size = len(tokens[i] | tokens[j])
        similarity = len(tokens[i] & tokens[j]) / union_size if union_size else 0.0
        if similarity >= 0.5:
            uf.union(i, j)

    patterns: list[CandidatePattern] = []
    for members in uf.groups(len(escalated)):
        if len(members) < MIN_GROUP_SIZE:
            continue

        member_cases = [escalated[i] for i in members]
        case_ids = tuple(c.id for c in member_cases)
        sample_reasons = sorted({c.escalation_reason for c in member_cases})
        headline = sample_reasons[0]

        rationale = (
            "Clustered escalation_reason text by shared significant words (>=50% token overlap, a "
            f"simple, deterministic approximation, not semantic understanding): cases "
            f"{', '.join(case_ids)} share this recurring reason: {'; '.join(sample_reasons)}."
        )
        question = CandidateQuestion(
            title=f'What should happen when a case is escalated for: "{headline}"?',
            description=(
                "A recurring escalation reason with no documented resolution found across these "
                "cases."
            ),
            rationale=rationale,
            supporting_case_ids=case_ids,
            candidate_explanation=(
                "these cases may share an undocumented handling approach for this escalation reason"
            ),
            alternative_explanations=(
                "each case may genuinely need individual judgement despite the similar wording",
                "the recurring reason may reflect an upstream process or retrieval issue rather than "
                "a policy gap",
                "the text similarity may be coincidental rather than a shared underlying cause",
            ),
            missing_evidence=(
                "whether any existing documented procedure already covers this escalation reason",
                "whether these cases share any other recorded facts beyond the escalation text itself",
            ),
            potential_impact=(
                "If a common handling approach is confirmed, it could become a documented rule for "
                "future escalations of this kind; if not, each case should continue to be judged "
                "individually."
            ),
        )
        patterns.append(
            CandidatePattern(
                title=f'Recurring escalation reason: "{headline}"',
                description=(
                    f"{len(member_cases)} cases were escalated for closely related reasons: "
                    + "; ".join(f'"{r}"' for r in sample_reasons)
                ),
                rationale=rationale,
                confidence="low",
                category="other",
                supporting_case_ids=case_ids,
                questions=(question,),
            )
        )
    return patterns


class FakeDiscoveryProvider:
    def discover(self, cases: list[CaseForDiscovery]) -> DiscoveryResult:
        patterns: list[CandidatePattern] = []
        patterns.extend(_conflicting_outcome_patterns(cases))
        patterns.extend(_missing_field_patterns(cases))
        patterns.extend(_escalation_reason_patterns(cases))
        return DiscoveryResult(patterns=tuple(patterns))
