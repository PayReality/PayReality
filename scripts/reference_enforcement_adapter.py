#!/usr/bin/env python3
"""REFERENCE / PROOF OF MECHANISM enforcement adapter -- NOT a SAP
integration, NOT production enforcement, NOT an enterprise Policy
Enforcement Point.

This script proves exactly one thing, and is careful to claim exactly
that and nothing more (PAYREALITY_FUTURE_VISION.md Part C, C9): "if a
proposed execution is routed through this adapter, execution requires
a valid, unexpired, correctly-scoped PayReality capability token." It
does NOT prove, and this file's own comments and output never claim,
that an enterprise target system cannot be reached through some OTHER
path that bypasses this adapter entirely -- that is a real, separate,
harder problem (a genuine enterprise PEP deployment, e.g. an API
gateway plugin, a sidecar, or a direct target-system integration) that
this script does not attempt to solve.

Verification mode: ONLINE verify-and-consume, calling POST
/v1/capability-tokens/verify for every proposed execution -- not
offline signature verification. This is the only mode this milestone
builds; a future offline-verification design (this adapter checking
the signature itself, against a locally cached public key, with its
own distributed replay-defense strategy) is a distinct architecture
this script deliberately does not attempt.

Trusted Integration Architecture, Phase 5: this same script now also
verifies a Capability issued for a Trusted-Adapter-mediated decision,
unchanged, since verification only ever depends on the token itself,
never on which runtime path issued it. The optional --environment/
--enforcement-binding-id flags let a checkpoint that knows which
Runtime Connection it enforces pin that expectation too; omit both to
verify without that additional binding check, the same as before this
phase.

Phase 6 (Reference End-to-End Enforcement Demonstration): two changes,
both about being honest rather than about new mechanism --

1. --principal is now exposed (the server-side check already existed
   since Phase 5; this script simply never let a caller use it).
2. Capability CONSUMPTION and DOWNSTREAM EXECUTION are now two
   separate, separately-reported steps, never one conflated message.
   Consuming a Capability means an execution PERMISSION was consumed;
   it is not proof the downstream business action completed. This
   script's own `execute_downstream_operation()` is a deliberately
   trivial, clearly-labeled reference/demo stand-in for "the real
   enterprise system did something" -- not a SAP connector, not a real
   integration, and its own success/failure is reported as a distinct
   fact from whether the Capability verified. See
   REFERENCE_ENFORCEMENT_DEMONSTRATION.md for the full walkthrough this
   script is one piece of.

--constraints-json accepts an arbitrary JSON object of exact-match
constraint values, for actions with no amount/currency at all (e.g.
ChangeSupplierBankDetails, this milestone's own reference scenario) --
--amount/--currency remain as convenience flags for the common
financial-action case and are folded into the same constraints dict,
never a second, parallel shape.

Usage:
    PAYREALITY_API_URL=http://localhost:8000 \
    PAYREALITY_OPERATOR_KEY=<the ADMIN_API_KEY configured on the backend> \
    python scripts/reference_enforcement_adapter.py \
        --audience reference-pep \
        --token <capability token from POST /v1/decisions/{id}/capability-token/from-review> \
        --action vendor_payment \
        --resource supplier:SUPPLIER_482 \
        --environment demo

Run the exact same command a second time with the exact same --token to
observe the required negative demonstration: the second attempt is
refused with "capability_token_already_consumed", and
execute_downstream_operation() is never called for it.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


def _api_url() -> str:
    return os.environ.get("PAYREALITY_API_URL", "http://localhost:8000")


def _operator_key() -> str:
    key = os.environ.get("PAYREALITY_OPERATOR_KEY", "")
    if not key:
        print("PAYREALITY_OPERATOR_KEY must be set", file=sys.stderr)
        sys.exit(2)
    return key


def _post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{_api_url()}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-PayReality-Operator-Key": _operator_key()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    capability_id: str | None
    decision_id: str | None
    reason: str | None


def verify_and_consume(
    token: str, audience: str, action: str, resource: str, constraints: dict,
    environment: str | None = None, enforcement_binding_id: str | None = None, principal: str | None = None,
) -> VerifyResult:
    """Calls the authoritative PayReality verify-and-consume path and
    nothing else. Never invokes the downstream reference operation
    itself -- that is a separate function, called by main() only after
    this one returns ok=True, so "the Capability was consumed" and "the
    reference business system ran" can never be reported as the same
    event even by accident.

    `environment`/`enforcement_binding_id`/`principal` are optional
    (Phase 5 sections 6/9): a real checkpoint that knows which Runtime
    Connection, environment, or Agent it expects should pass whichever
    it knows, so a Capability that doesn't match is rejected here
    rather than silently accepted."""
    request_body = {
        "token": token, "audience": audience, "action": action, "resource": resource,
        "constraints": constraints,
    }
    if environment is not None:
        request_body["environment"] = environment
    if enforcement_binding_id is not None:
        request_body["enforcement_binding_id"] = enforcement_binding_id
    if principal is not None:
        request_body["principal"] = principal
    status, body = _post("/v1/capability-tokens/verify", request_body)
    if status == 200:
        return VerifyResult(ok=True, capability_id=body["capability_id"], decision_id=body["decision_id"], reason=None)
    return VerifyResult(ok=False, capability_id=None, decision_id=None, reason=body.get("detail", f"http_{status}"))


def execute_downstream_operation(action: str, resource: str, constraints: dict) -> bool:
    """The reference/demo stand-in for "the real enterprise system
    performed the action" -- deliberately trivial (prints and returns
    True), never a real SAP/Workday/ServiceNow connector, and never
    called unless verify_and_consume() above already returned ok=True.
    A real deployment replaces this one function with whatever actually
    calls its own enterprise system; nothing about the verification
    contract above depends on what this function does. Its own return
    value is reported as a SEPARATE fact from Capability consumption --
    PayReality has no way to know, and this script makes no claim, that
    this step is cryptographically tied to anything: it is exactly as
    trustworthy as the reference PEP process running it, no more."""
    print(f"REFERENCE BUSINESS SYSTEM: executing action={action} resource={resource} constraints={constraints}")
    print("REFERENCE BUSINESS SYSTEM: completed (this is a reference stand-in, not a real enterprise system)")
    return True


def run(
    token: str, audience: str, action: str, resource: str, constraints: dict,
    environment: str | None = None, enforcement_binding_id: str | None = None, principal: str | None = None,
) -> bool:
    """Orchestrates the two separate steps and prints a result for each,
    never merging them into one line. Returns True only if both the
    Capability verified/consumed AND the reference downstream operation
    itself reported success."""
    result = verify_and_consume(
        token, audience, action, resource, constraints,
        environment=environment, enforcement_binding_id=enforcement_binding_id, principal=principal,
    )
    if not result.ok:
        print(f"CAPABILITY REJECTED: {result.reason}")
        print("DOWNSTREAM EXECUTION: not attempted (a rejected Capability never reaches the reference business system)")
        return False

    print(f"CAPABILITY VERIFIED AND CONSUMED: capability={result.capability_id} decision={result.decision_id}")
    executed = execute_downstream_operation(action, resource, constraints)
    print(f"DOWNSTREAM EXECUTION: {'executed successfully' if executed else 'execution failed'}")
    print(
        "NOTE: Capability consumption proves an execution permission was used exactly once. "
        "It does not by itself prove the downstream business system's own action succeeded -- "
        "that is this separate, second line."
    )
    return executed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--amount", default=None, help="Convenience flag, folded into --constraints-json; omit for a non-financial action.")
    parser.add_argument("--currency", default=None)
    parser.add_argument(
        "--constraints-json", default=None,
        help="Arbitrary exact-match constraints as a JSON object, for an action with no amount/currency "
             "(e.g. a supplier bank-details change). Merged with --amount/--currency if both are given.",
    )
    parser.add_argument(
        "--environment", default=None,
        help="Optional (Trusted Integration Architecture Phase 5): pin the expected Runtime Connection "
             "environment (e.g. production, demo) against the capability's own signed claim.",
    )
    parser.add_argument(
        "--enforcement-binding-id", default=None,
        help="Optional (Phase 5): pin the expected Runtime Connection id against the capability's own signed claim.",
    )
    parser.add_argument(
        "--principal", default=None,
        help="Optional (Phase 5 section 6/9, exposed here in Phase 6): pin the expected principal name "
             "against the capability's own signed claim.",
    )
    args = parser.parse_args()

    constraints: dict = json.loads(args.constraints_json) if args.constraints_json else {}
    if args.amount is not None:
        constraints["amount"] = args.amount
    if args.currency is not None:
        constraints["currency"] = args.currency

    ok = run(
        args.token, args.audience, args.action, args.resource, constraints,
        environment=args.environment, enforcement_binding_id=args.enforcement_binding_id, principal=args.principal,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
