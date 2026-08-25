# Unknown Fact Behavior: DENY vs. HUMAN_REVIEW

**Status: current, documenting existing, verified behavior. No decision-engine change accompanies this document.**

## The behavior, stated plainly

When a Runtime Policy's condition references a trusted enterprise fact (`enterprise_knowledge.<key>`) and that fact is **missing, expired, or in unresolved contradiction between two trusted sources**, the condition simply does not evaluate true. This is identical, mechanically, to any other unsatisfied condition (e.g. an amount over a configured limit) -- Runtime Authority does not treat "fact unknown" as a special case with its own outcome.

The consequence that surprised an early test assumption during development: **with only a single authored `ALLOW` policy for a scope, an unresolved fact resolves the decision to `DENY`, not `HUMAN_REVIEW`.** The compiled bundle's own existing default -- present before Trusted Enterprise Facts existed, unrelated to this feature, and untouched by it -- is that an unmatched scope falls through to `DENY`. `HUMAN_REVIEW` is not the automatic consequence of "a fact was unresolved"; it is the consequence of a rule that was *specifically authored* to require review, matching, or fail-closed engine behavior (no active policy, an OPA timeout, an ambiguous OPA result).

**Both outcomes are genuinely fail-closed** -- neither is ALLOW, and no unresolved fact can ever silently produce ALLOW. But `DENY` and `HUMAN_REVIEW` are not the same outcome, and an organization that wants the second one for this case has to author it.

## Why this is deliberate, not a bug

Runtime Authority does not invent an escalation path an organization did not define. If an unresolved fact automatically became `HUMAN_REVIEW` platform-wide, that would be Runtime Authority silently overriding what the organization's own authored policy set actually says should happen when a condition fails -- exactly the kind of default this platform's design has consistently avoided elsewhere (compare: an ambiguous OPA result already fails to `HUMAN_REVIEW` only because *that specific branch* is engine-level and pre-declared, not because "ambiguity" is a universal trigger applied after the fact to every possible condition).

## Worked example

**Policy 1 only:**

```
ALLOW  vendor_payment
WHEN   amount <= 50000
AND    enterprise_knowledge.supplier_approved == true
```

If `supplier_approved` is unknown (missing, expired, or contradictory) for the relevant subject:
- The `ALLOW` rule's condition is not satisfied.
- No other rule matches.
- Outcome: **DENY**.

**If the organization instead wants a human to look at the unresolved case**, it must author a second, explicit rule for the same scope:

```
Policy 1:
ALLOW  vendor_payment
WHEN   amount <= 50000
AND    enterprise_knowledge.supplier_approved == true

Policy 2:
REQUIRE_HUMAN_REVIEW  vendor_payment
WHEN   amount <= 50000
AND    enterprise_knowledge.supplier_approved != true
```

`REQUIRE_HUMAN_REVIEW` is the real, existing `Effect` value this platform already supports (`domain/runtime_policy/effects.py`) -- resolving to the real `HUMAN_REVIEW` decision outcome. Nothing new was introduced to make this example work; it uses only what already exists.

## What this means for policy authors

- Authoring a fact-gated `ALLOW` condition without a matching fallback rule means an unresolved fact denies the action, not escalates it.
- If escalation-on-unresolved is the intended behavior, it must be authored explicitly, using the negation of the same condition, exactly as the worked example shows.
- This is symmetric with how amount-threshold escalation already works in this platform's own existing policies (e.g. an `ALLOW ... amount <= 50000` paired with a `REQUIRE_HUMAN_REVIEW ... amount > 50000` sibling rule for the same scope) -- the same authoring discipline, applied to a fact condition instead of a numeric one.

## RECOMMENDED FOLLOW-UP (not implemented in this milestone)

Inspected the policy-authoring UI (`ConditionRow.tsx`, `PolicyWorkspacePage.tsx`) directly: there is currently **no in-UI guidance anywhere near condition or effect authoring** that surfaces this distinction to a reviewer. A reviewer authoring `enterprise_knowledge.supplier_approved == true` with only an `ALLOW` effect has no signal, in the product itself, that an unresolved fact denies rather than escalates. This is a genuine clarity gap, not a hypothetical one -- but per this milestone's explicit scope (no speculative UI), it is recorded here as a recommendation, not built: a short, static help note near the condition editor (or `HelpIcon` content) explaining this exact distinction, surfaced specifically when a condition references an `enterprise_knowledge.` field.
