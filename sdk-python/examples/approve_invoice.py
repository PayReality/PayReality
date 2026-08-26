"""What happens when `operation` doesn't match a recognized action yet.
This is deliberately not a "happy path" example: it shows the
platform's real, honest fallback behaviour, not a fabricated success
case.

`operation` (not `resource`, since Domain Generalization Milestone's
SDK 0.4.0 -- see agent.py's own version-history comments) becomes the
Runtime Policy action. PayReality recognizes a small explicit baseline
(vendor_payment, purchase_order_create, wire_transfer, disable_user)
plus whatever action any of the calling organization's own active
policies actually govern -- "Approve Invoice" isn't either, so this
authorize() call is expected to come back HUMAN_REVIEW: an unrecognized
action never silently defaults to ALLOW, it always escalates to a
human instead (fail-closed by design, see docs/API_SPECIFICATION.md).
"""

import os

from payreality import Agent

agent = Agent(api_key=os.environ["PAYREALITY_API_KEY"])
agent.register(name="AP Automation Bot", principal="Finance Manager")

decision = agent.authorize(
    principal="Finance Manager",
    operation="Approve Invoice",
    resource="invoice:INV-77341",
    resource_data={"amount": 4200, "vendor": "Acme Supplies"},
)

print(f"Outcome: {decision.outcome}")
print(f"Reason: {decision.reason}")
assert decision.requires_human_review, "an unrecognized resource should escalate, never silently allow"
