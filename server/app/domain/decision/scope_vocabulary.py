"""Scope vocabulary: spec Section 12.6, generalized (Domain Generalization
Milestone) to no longer be exclusively financial.

The original spec 9.3/12.6 rule remains the invariant: "an unrecognized
requested_action always resolves to HUMAN_REVIEW rather than silently
matching the wrong Mandate." What "recognized" means has widened from a
single hardcoded enumeration to two layers, so a genuinely new,
non-financial action type becomes recognizable the moment an
organization authors and activates a real RuntimePolicy for it, without
a code deployment:

1. KNOWN_SCOPES -- the original fixed baseline, unchanged, always
   recognized regardless of organization or policy state (kept exactly
   as the spec's own extension mechanism describes: "a schema change,
   not a runtime configuration change").
2. Whatever action any of the calling organization's currently ACTIVE
   RuntimePolicies actually govern (runtime_policy_service.
   list_active_scope_actions) -- since Compiler V2's own vocabulary
   validation (compiler_v2.GENERIC_VOCABULARY) already gates which
   actions can be compiled and activated in the first place, this can
   never silently admit something the compiler itself would have
   rejected; it only removes the need to *also* hand-maintain this
   frozenset every time a real, already-authored, already-active policy
   exists for a new action.

Used by the intent service (not the Rego bundle itself) to short-circuit
an unrecognized action to HUMAN_REVIEW before OPA is ever queried; this
is a different case from "a recognized action with no matching Mandate",
which the compiled Rego correctly resolves to DENY (spec 9.3 draws this
exact distinction).
"""

KNOWN_SCOPES = frozenset(
    {
        "vendor_payment",
        "purchase_order_create",
        "wire_transfer",
    }
)


def is_recognized_scope(action: str, active_scope_actions: frozenset[str] = frozenset()) -> bool:
    """`active_scope_actions` defaults to empty so every existing caller
    (tests included) that doesn't pass it keeps exactly today's
    behavior -- KNOWN_SCOPES alone. intent_service.submit_intent is the
    one real caller that passes the organization's actual active-policy
    action set."""
    return action in KNOWN_SCOPES or action in active_scope_actions
