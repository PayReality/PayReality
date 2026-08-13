"""Deterministic fake RuntimePolicyExtractionProvider for tests and for
running the AI Policy Builder without a real AI provider configured
(neither Azure AI Foundry nor ANTHROPIC_API_KEY)."""

from app.domain.ai_policy_builder.provider import CandidateCondition, CandidateRuntimePolicy


class FakeRuntimePolicyExtractionProvider:
    def __init__(self, candidates: list[CandidateRuntimePolicy] | None = None):
        self._candidates = candidates or [
            CandidateRuntimePolicy(
                name="Regional Controller EMEA - Vendor Payment Limit",
                principal="Regional Controller, EMEA",
                action="vendor_payment",
                effect="require_human_review",
                confidence=0.9,
                source_excerpt="The Regional Controller may approve vendor payments up to $50,000.",
                source_location="page 1",
                conditions=(CandidateCondition(field="amount", operator="<=", value=50000),),
                evidence_required=True,
                metadata_tags=("finance",),
            )
        ]

    def extract(self, document_text: str) -> list[CandidateRuntimePolicy]:
        return list(self._candidates)
