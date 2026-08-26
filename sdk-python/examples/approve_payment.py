"""The exact flow from the SDK's own pitch: authorize a vendor payment,
then branch on the outcome. Assumes `register_agent.py` has already been
run once (so a local identity exists for this api_key's default agent).
"""

import os

from payreality import Agent

agent = Agent(api_key=os.environ["PAYREALITY_API_KEY"])
# In a real integration this Agent already has a local identity from a
# prior register() call (see register_agent.py); this example calls
# register() again for it to be runnable standalone, which is a no-op
# once that identity already exists.
agent.register(name="AP Automation Bot", principal="Finance Manager")

decision = agent.authorize(
    principal="Finance Manager",
    operation="vendor_payment",
    resource="invoice:INV-58211",
    resource_data={
        "amount": 85000,
        "vendor": "ABC Ltd",
    },
)

if decision.allowed:
    print(f"Allowed. Evidence: {decision.evidence_id}")
    # execute_payment(...)
elif decision.requires_human_review:
    print(f"Sent for human review. decision_id={decision.decision_id}")
    print("Poll agent.get_decision(decision.decision_id) until it resolves.")
else:
    print(f"Denied: {decision.reason}")
    # stop()
