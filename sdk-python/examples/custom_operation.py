"""Two things this example shows:

1. A genuinely non-financial operation/resource pair (Disable User /
   a privileged production account), the same universal-vocabulary
   shape RESOURCE_MODEL.md and OPERATION_MODEL.md describe. No `amount`
   or `currency` anywhere -- `disable_user` is one of the actions the
   platform recognizes out of the box (Domain Generalization Milestone),
   proof that the Decision Engine's action vocabulary is no longer
   financial-only. `resource` is the real object this action concerns,
   an opaque identifier ("account:USR-829"), never normalized -- unlike
   `operation`, which becomes the actual Runtime Policy action.
2. `decision.raise_for_outcome()`: an alternative to checking
   `decision.allowed` by hand, for callers who prefer exception-flow
   control, mirroring `requests.Response.raise_for_status()`.
"""

import os

from payreality import Agent, AuthorizationDenied, HumanReviewRequired

agent = Agent(api_key=os.environ["PAYREALITY_API_KEY"])
agent.register(name="Security-Agent", principal="CISO")

decision = agent.authorize(
    principal="CISO",
    operation="Disable User",
    resource="account:USR-829",
    resource_data={
        "environment": "production",
        "privileged_account": True,
    },
    metadata={"shift": "night", "requested_by": "J. Nkosi"},
)

try:
    decision.raise_for_outcome()
    print("Disabled.")
except AuthorizationDenied as e:
    print(f"Denied: {e}")
except HumanReviewRequired as e:
    print(f"Escalated for human review: {e} (decision_id={e.decision.decision_id})")
