"""Integration Kit v1: the canonical zero-to-first-Decision path, in one
runnable script. Every call here is either a real SDK method or a real,
existing API endpoint -- nothing here is invented.

This script deliberately covers ground the other examples don't:
creating a first Runtime Policy through its real, unmodified
create -> submit-for-review -> approve -> compile -> deploy lifecycle,
not just calling authorize() against a policy that already exists.

Organization creation (step 0) is NOT a self-serve step today: it
requires the platform Operator Key, an administrative action. This
script assumes you already have one (from the PayReality team, or your
own self-hosted/eval environment) -- it does not, and cannot, fabricate
a signup flow the platform doesn't have.

Usage:
    PAYREALITY_API_URL=http://localhost:8000 \
    PAYREALITY_OPERATOR_KEY=<the platform Operator Key> \
    python examples/quickstart.py
"""

import os
import time

import requests

from payreality import Agent

API_URL = os.environ.get("PAYREALITY_API_URL", "http://localhost:8000")
OPERATOR_KEY = os.environ["PAYREALITY_OPERATOR_KEY"]


def _admin_post(path: str, json: dict | None = None, organization_id: str | None = None) -> dict:
    headers = {"X-PayReality-Operator-Key": OPERATOR_KEY}
    if organization_id:
        headers["X-PayReality-Organization-Id"] = organization_id
    response = requests.post(f"{API_URL}{path}", json=json or {}, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json() if response.content else {}


def main() -> None:
    started = time.monotonic()

    # --- Step 0: organization. Admin-provisioned today, not self-serve. ---
    org = _admin_post(
        "/v1/organizations",
        {"name": "Quickstart Org", "owner_email": "owner@example.com", "owner_name": "Quickstart Owner"},
    )
    organization_id = org["organization"]["id"]
    print(f"[0] Organization: {organization_id}")

    # --- Step 1: register an Agent (real SDK, no manual signing). ---
    agent = Agent(api_key=OPERATOR_KEY, organization_id=organization_id, base_url=API_URL)
    registered = agent.register(name="Quickstart Agent", principal="Quickstart Principal")
    print(f"[1] Agent registered: {registered.agent_id}")

    # --- Step 2: one starter policy, through the real, unmodified lifecycle. ---
    # "Low-risk reference action allowed" starter template -- see
    # INTEGRATION_KIT.md for the other two starter templates (Human Review
    # for a sensitive account change / a high-value financial action).
    # `purchase_order_create` is one of the platform's real, closed
    # vocabulary of canonical actions (server/app/domain/decision/
    # scope_vocabulary.py) -- an invented action name would fail
    # compilation, not silently succeed.
    policy = _admin_post(
        "/v1/runtime-policies",
        {
            "name": "Quickstart: low-risk reference action allowed",
            "scope": {"principal": "Quickstart Principal", "action": "purchase_order_create"},
            "conditions": [],
            "effect": "allow",
        },
        organization_id=organization_id,
    )
    policy_key = policy["policy_key"]
    _admin_post(f"/v1/runtime-policies/{policy_key}/submit-for-review", organization_id=organization_id)
    _admin_post(f"/v1/runtime-policies/{policy_key}/approve", {"approver": "quickstart-script"}, organization_id=organization_id)
    compiled = _admin_post(f"/v1/runtime-policies/{policy_key}/compile", organization_id=organization_id)
    if not compiled["ok"]:
        raise SystemExit(f"policy compile failed: {compiled['errors']}")
    _admin_post(f"/v1/runtime-policies/{policy_key}/deploy", organization_id=organization_id)
    print(f"[2] Policy deployed: {policy_key}")

    # --- Step 3: one test action, through the real SDK. ---
    decision = agent.authorize(
        principal="Quickstart Principal",
        operation="purchase_order_create",
        resource="po:quickstart-001",
    )
    print(f"[3] Decision: {decision.outcome} (decision_id={decision.decision_id})")

    elapsed = time.monotonic() - started
    print(f"\nDone in {elapsed:.1f}s of script execution time (excludes reading this script, "
          f"installing the SDK, or obtaining an Operator Key -- see INTEGRATION_KIT.md for the "
          f"full, honest 'time to first Decision' discussion).")

    print("\nOptional next steps: see INTEGRATION_KIT.md for the Trusted Adapter template "
          "(payreality.adapter_templates) and Capability enforcement (payreality.enforcement).")


if __name__ == "__main__":
    main()
