"""Product Experience V3.2, section 24: GET /v1/runtime-policies/vocabulary
additively exposes condition_fields/trusted_context_prefix so the manual
builder's condition field selector can offer only fields Compiler V2's
own is_valid_field would actually accept, instead of free text a user
could invent that PayReality can never evaluate.
"""

from app.domain.compiler_v2.compiler_v2 import GENERIC_VOCABULARY
from app.routers.runtime_policies import get_vocabulary


def test_vocabulary_exposes_condition_fields_matching_compiler_v2():
    result = get_vocabulary()
    assert set(result["condition_fields"]) == GENERIC_VOCABULARY.known_intent_fields
    for field in result["condition_fields"]:
        assert GENERIC_VOCABULARY.is_valid_field(field)


def test_vocabulary_exposes_the_trusted_context_prefix():
    result = get_vocabulary()
    assert result["trusted_context_prefix"] == "context."
    assert GENERIC_VOCABULARY.is_valid_field("context.supplier_approved")


def test_vocabulary_exposes_actions_matching_the_generic_vocabulary():
    """Trusted Integration Architecture, Phase 6.1 (Part C): this
    endpoint switched from FINANCIAL_VOCABULARY to GENERIC_VOCABULARY --
    see get_vocabulary's own docstring for the real, pre-existing gap
    this closes. It must now expose every generic action too, not only
    the financial ones."""
    result = get_vocabulary()
    assert result["actions"] == sorted(GENERIC_VOCABULARY.known_actions)
    assert "disable_user" in result["actions"]
    assert "supplier_bank_details_change" in result["actions"]
    assert "vendor_payment" in result["actions"]
