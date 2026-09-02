"""Developer Distribution & Sandbox v1: the canonical zero-to-first-
Decision path for a developer with NO prior PayReality relationship --
no Operator Key, no repository checkout, no admin intervention. Every
call here is either a real SDK method or a real, existing API endpoint;
nothing is invented.

Step 0 (get a sandbox) is the one genuinely new, self-service piece
this milestone adds: POST /v1/sandbox/organizations, public, rate-
limited, capped at one per email. It provisions a real, isolated
Organization (environment="sandbox", the same authority pipeline as
production, never a second/simplified engine), one ready-to-use API
key, and one starter Runtime Policy -- deployed through its real,
unmodified create -> submit-for-review -> approve -> compile -> deploy
lifecycle, not a shortcut.

Usage (nothing but a real, deployed backend's URL is required):
    PAYREALITY_API_URL=https://api.aisecurewatch.com \
    python examples/quickstart.py
"""

import os
import time

import requests

from payreality import Agent

API_URL = os.environ.get("PAYREALITY_API_URL", "https://api.aisecurewatch.com")


def main() -> None:
    started = time.monotonic()

    # --- Step 0: get a sandbox. Public, self-service, rate-limited. ---
    email = f"quickstart+{int(time.time())}@example.com"
    response = requests.post(
        f"{API_URL}/v1/sandbox/organizations", json={"email": email}, timeout=15,
    )
    response.raise_for_status()
    sandbox = response.json()
    print(f"[0] Sandbox organization: {sandbox['organization_id']}")
    print(f"    Starter policy already deployed: {sandbox['starter_policy_key']}")

    # --- Step 1: register a test Agent (real SDK, no manual signing). ---
    agent = Agent(bearer_token=sandbox["api_key"], base_url=API_URL)
    registered = agent.register(name="Quickstart Agent", principal="Sandbox Principal")
    print(f"[1] Agent registered: {registered.agent_id}")

    # --- Step 2: the starter policy already exists -- nothing to do here. ---
    # (See INTEGRATION_KIT.md's other two starter templates -- Human
    # Review for a sensitive account change / a high-value financial
    # action -- for what to configure next once this first run works.)

    # --- Step 3: one test action, through the real SDK. ---
    decision = agent.authorize(
        principal="Sandbox Principal",
        operation="purchase_order_create",
        resource="po:quickstart-001",
    )
    print(f"[3] Decision: {decision.outcome} (decision_id={decision.decision_id})")

    elapsed = time.monotonic() - started
    print(f"\nDone in {elapsed:.1f}s of script execution time against the real, live backend "
          f"(excludes reading this script or installing the SDK -- see INTEGRATION_KIT.md for "
          f"the full, honest 'time to first Decision' discussion, including what was and wasn't "
          f"actually measured).")

    print("\nOptional next steps: see INTEGRATION_KIT.md for the Trusted Adapter template "
          "(payreality.adapter_templates) and Capability enforcement (payreality.enforcement) --"
          " both work against this same sandbox organization, no production access needed.")


if __name__ == "__main__":
    main()
