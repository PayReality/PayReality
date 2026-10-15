"""Deterministic FakeDiscoveryProvider: the AI discovery feature's no-API-
key, zero-external-call, zero-cost fallback -- the path every deployment
without ANTHROPIC_API_KEY (or Azure AI Foundry) configured actually runs
in production, not a throwaway stub. Unlike the sibling fake providers
(domain/ai_policy_builder/fake_provider.py, domain/ai_authority_builder/
fake_provider.py), which return a single hardcoded, document-shaped
example because their real input is unstructured document text, this
feature's input is real, structured DICase rows -- so this fake provider
can and does run genuine, deterministic analysis over the actual data it's
given, not a canned response. It is the single most-tested code path in
this feature: most organisations will run on this provider, possibly
forever.

Three independent heuristics, each producing zero or more
CandidatePattern rows (each carrying zero or more CandidateQuestion rows
of its own):

1. `_conflicting_outcome_patterns` (run first -- the brief's own "single
   most defensible heuristic available"): groups of two or more cases
   whose facts are identical except for at most one field, but whose
   recorded human_decision differs. This is a direct, concrete,
   unambiguous signal that the organisation has not settled how that one
   differing fact should affect the outcome -- not a correlation or a
   guess. Confidence: "high".
2. `_missing_field_patterns`: a fact key that's present (non-null) on at
   least one case in this batch but absent (missing or null) on at least
   two others -- inconsistent data collection for what looks like the
   same kind of decision. Confidence: "medium" (a real, precise signal
   about the data, but not itself proof the field *should* be required).
3. `_escalation_reason_patterns`: clusters cases whose escalation_reason
   text shares at least 50% of its significant words (a simple, bounded,
   deterministic Jaccard-similarity union-find clustering -- no ML, no
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
        field_desc = ", ".join(differing_fields) if differing_fields else "no recorded fields"
        decisions_seen = sorted({json.dumps(c.human_decision, sort_keys=True) for c in member_cases})

        rationale = (
            f"Compared every pair of cases with a recorded human_decision: cases "
            f"{', '.join(case_ids)} have facts that match on every field except {field_desc}, "
            f"yet their recorded decisions disagree ({'; '.join(decisions_seen)}). This is a direct "
            "signal that the organisation has not settled how this fact should affect the outcome, "
            "not an inferred correlation."
        )
        question = CandidateQuestion(
            title=f"What should determine the decision when {field_desc} differs?",
            description=(
                f"{len(member_cases)} otherwise-identical cases were decided differently depending "
                f"on {field_desc}. Answering this would resolve the ambiguity for every future case "
                "like it."
            ),
            rationale=rationale,
            supporting_case_ids=case_ids,
        )
        patterns.append(
            CandidatePattern(
                title=f"Conflicting decisions on near-identical cases ({field_desc})",
                description=(
                    f"{len(member_cases)} cases have facts that match except for {field_desc}, but "
                    f"were decided differently: {'; '.join(decisions_seen)}."
                ),
                rationale=rationale,
                confidence="high",
                category="conflicting_rules",
                supporting_case_ids=case_ids,
                questions=(question,),
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
            f"not record it at all, while {len(present)} other case(s) in this batch do, suggesting "
            "this fact is sometimes collected and sometimes not for what looks like the same kind of "
            "decision."
        )
        question = CandidateQuestion(
            title=f"Is '{key}' required to decide this kind of case?",
            description=(
                f"Some cases record '{key}' and others don't. Answering this would clarify whether "
                "it's required, and what to do when it's missing."
            ),
            rationale=rationale,
            supporting_case_ids=case_ids,
        )
        patterns.append(
            CandidatePattern(
                title=f"Cases missing '{key}'",
                description=(
                    f"{len(absent)} of {len(cases)} cases are missing the '{key}' fact, which is "
                    f"present on {len(present)} other case(s) in this workflow."
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
