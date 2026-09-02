# External Quickstart

For a developer who has never touched this repository. No repository checkout, no Operator Key, no
admin intervention required for any step below.

## How do I get test access?

```bash
curl -X POST https://api.aisecurewatch.com/v1/sandbox/organizations \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'
```

Returns, once, immediately:
- `api_key` -- an SDK-ready credential.
- `owner_email` / `owner_temporary_password` -- a dashboard login, if you want the UI too.
- `starter_policy_key` -- a Runtime Policy already created, approved, and deployed for you, so your
  first request below can return a real `ALLOW`, not just a default `HUMAN_REVIEW`.

This creates a real, isolated Organization on the real backend (`environment="sandbox"`) -- the
same authority pipeline production uses, never a mock or a simplified engine. Limited to one per
email address, and rate-limited; see `INTEGRATION_KIT.md`'s Sandbox section for the exact numbers
and what a sandbox does and doesn't let you do.

## How do I install the SDK?

```bash
pip install -e sdk-python/
```

from a checkout of the SDK's own subdirectory. This is the real, current install path -- see
`INTEGRATION_KIT.md`'s Installation section for the honest current state of public PyPI
distribution (the package is ready; publishing it is not yet complete).

## How do I configure the SDK?

```python
from payreality import Agent

agent = Agent(bearer_token="<api_key from above>", base_url="https://api.aisecurewatch.com")
```

`bearer_token` is a real, scoped, revocable credential -- not a generic placeholder API key, and
not the platform-wide Operator Key (which this flow never touches at all).

## How do I register my first test Agent?

```python
registered = agent.register(name="My Test Agent", principal="Sandbox Principal")
print(registered.agent_id)
```

## How do I send my first action?

```python
decision = agent.authorize(
    principal="Sandbox Principal",
    operation="purchase_order_create",
    resource="po:test-001",
)
print(decision.outcome)
```

## What does ALLOWED mean?

`decision.outcome == "ALLOW"`: the action was within the authority your sandbox's starter policy
already delegates. Real Evidence and an Authorization Receipt exist for it -- see
`SDK_REFERENCE.md`'s `Decision` documentation for how to retrieve them.

## What does NOT ALLOWED mean?

`decision.outcome == "DENY"`: the action was evaluated and explicitly refused, not merely unknown.
`decision.reason` names why.

## What does NEEDS HUMAN APPROVAL mean?

`decision.outcome == "HUMAN_REVIEW"`: the request needs a named reviewer's decision before anything
proceeds. `agent.wait_for_resolution(decision.decision_id)` blocks (with a real timeout) until it
resolves -- see `SDK_QUICKSTART.md` step 4 for the full pattern, including what a resolution does
and does not mean for the original Decision (it is never rewritten).

## What should I try next?

- `sdk-python/examples/quickstart.py` runs everything above in one script.
- Add a Human-Review or high-value-financial starter policy of your own -- `INTEGRATION_KIT.md`'s
  "Starter policy templates".
- Trusted observation of a real attempted operation, independent of what your Agent declares --
  `INTEGRATION_KIT.md`'s "Adapter Template" (Stage 2).
- Controlled execution with a real, single-use Capability Authorization at your own enforcement
  boundary -- `INTEGRATION_KIT.md`'s "Enforcement Middleware" (Stage 3).
- The full worked example, end to end -- `INTEGRATION_KIT.md`'s "Integration recipe: Supplier bank
  details change".

None of Stage 2 or Stage 3 requires production access; all of it works against the same sandbox
organization you already have.
