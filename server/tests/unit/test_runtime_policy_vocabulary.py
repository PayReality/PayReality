"""Product Experience V3.2, section 24: GET /v1/runtime-policies/vocabulary
additively exposes condition_fields/trusted_context_prefix so the manual
builder's condition field selector can offer only fields Compiler V2's
own is_valid_field would actually accept, instead of free text a user
could invent that PayReality can never evaluate.
"""

from app.domain.compiler_v2.compiler_v2 import FINANCIAL_VOCABULARY
from app.routers.runtime_policies import get_vocabulary


def test_vocabulary_exposes_condition_fields_matching_compiler_v2():
    result = get_vocabulary()
    assert set(result["condition_fields"]) == FINANCIAL_VOCABULARY.known_intent_fields
    for field in result["condition_fields"]:
        assert FINANCIAL_VOCABULARY.is_valid_field(field)


def test_vocabulary_exposes_the_trusted_context_prefix():
    result = get_vocabulary()
    assert result["trusted_context_prefix"] == "context."
    assert FINANCIAL_VOCABULARY.is_valid_field("context.supplier_approved")


def test_vocabulary_still_exposes_actions_unchanged():
    result = get_vocabulary()
    assert result["actions"] == sorted(FINANCIAL_VOCABULARY.known_actions)
