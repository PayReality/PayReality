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

Usage:
    PAYREALITY_API_URL=http://localhost:8000 \
    PAYREALITY_OPERATOR_KEY=<the ADMIN_API_KEY configured on the backend> \
    python scripts/reference_enforcement_adapter.py \
        --audience sap-reference-adapter \
        --token <capability token from POST /v1/decisions/{id}/capability-token> \
        --resource invoice-123 \
        --amount 48000 --currency USD
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


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


def attempt_execution(token: str, audience: str, action: str, resource: str, amount: str, currency: str) -> bool:
    """Refuses execution unless verify-and-consume succeeds. Every
    rejection reason below (missing/invalid/expired/consumed token,
    audience/action/resource/amount mismatch) is a real, distinct HTTP
    status the backend returns -- this function never guesses at why a
    rejection happened, it reports exactly what the backend said."""
    status, body = _post(
        "/v1/capability-tokens/verify",
        {"token": token, "audience": audience, "action": action, "resource": resource,
         "constraints": {"amount": amount, "currency": currency}},
    )
    if status == 200:
        print(f"EXECUTION ACCEPTED: capability {body['capability_id']} consumed for decision {body['decision_id']}")
        print(f"  (mock action) would now execute: resource={resource} amount={amount} {currency}")
        return True

    reason = body.get("detail", f"http_{status}")
    print(f"EXECUTION REFUSED: {reason}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args()

    ok = attempt_execution(args.token, args.audience, args.action, args.resource, args.amount, args.currency)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
