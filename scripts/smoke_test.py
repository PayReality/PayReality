#!/usr/bin/env python3
"""End-to-end Runtime Authority smoke test, run against a real deployed
backend (not TestClient, not localhost-by-default): Request -> Policy
Evaluation -> Deterministic Decision -> Cryptographic Evidence -> Evidence
Verification -> Assurance counts.

This exercises the full pipeline the way a real Agent would: it generates
its own ED25519 keypair, registers a real Agent against a real Principal,
signs a real Intent, and checks the Evidence that comes back actually
verifies. No mocking anywhere in this script.

Usage:
    pip install pynacl   # only third-party dependency; stdlib does the HTTP
    PAYREALITY_API_URL=https://api.aisecurewatch.com \
    PAYREALITY_OPERATOR_KEY=<the ADMIN_API_KEY set on the deployed service> \
    PAYREALITY_ORGANIZATION_ID=<the target organization's id> \
    python scripts/smoke_test.py

PayReality Enterprise v1.0 (Milestone 2, Multi-Tenant Foundation) made
the Operator Key platform-admin-only: it must now name its target
organization explicitly (X-PayReality-Organization-Id) on every org-
scoped request -- PAYREALITY_ORGANIZATION_ID is that target. Use
GET /v1/organizations (also Operator-Key-gated) to discover a valid id.

Exit code 0 means every stage passed. Any failure prints exactly which
stage failed and why, then exits non-zero. This is meant to be safe to
wire into a deploy pipeline as a post-deploy gate, not just run by hand.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import nacl.signing

BASE_URL = os.environ.get("PAYREALITY_API_URL", "http://localhost:8000").rstrip("/")
OPERATOR_KEY = os.environ.get("PAYREALITY_OPERATOR_KEY", "")
ORGANIZATION_ID = os.environ.get("PAYREALITY_ORGANIZATION_ID", "")

_passed = []
_failed = []


def _operator_headers(extra: dict | None = None) -> dict:
    """PayReality Enterprise v1.0 (Milestone 2) made the Operator Key
    platform-admin-only: it must now name its target organization
    explicitly on every org-scoped request. Included on every operator-
    keyed call in this script regardless of whether that specific
    endpoint happens to require it -- harmless where it isn't needed."""
    headers = {"X-PayReality-Operator-Key": OPERATOR_KEY, "X-PayReality-Organization-Id": ORGANIZATION_ID}
    if extra:
        headers.update(extra)
    return headers


def _parse_body(raw: bytes) -> dict:
    """A hosting edge (e.g. Render free tier cold-starting an instance) can
    return a plain-text error page instead of the app's own JSON response;
    surface that as data instead of crashing the whole run on a
    JSONDecodeError, since it's a real, observed condition of this
    deployment's zero-cost topology, not a hypothetical one."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_non_json_body": raw.decode("utf-8", errors="replace")}


def _request(method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, _parse_body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _parse_body(e.read())


def step(name: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                _passed.append(name)
                print(f"  PASS  {name}")
                return result
            except AssertionError as e:
                _failed.append(name)
                print(f"  FAIL  {name}: {e}")
                raise SystemExit(1)
        return wrapper
    return decorator


@step("liveness: GET /health")
def check_health():
    # A handful of retries absorbs a cold-starting free-tier instance or a
    # transient edge blip (both observed in practice against Render's free
    # plan) without masking a genuinely down backend, which would still
    # fail every one of these attempts.
    last_status, last_body = None, None
    for attempt in range(5):
        last_status, last_body = _request("GET", "/health")
        if last_status == 200 and last_body.get("status") == "ok":
            return
        time.sleep(2 * (attempt + 1))
    assert last_status == 200, f"status {last_status}, body {last_body}"
    assert last_body.get("status") == "ok", last_body


@step("readiness: GET /health/ready (database + OPA both reachable)")
def check_ready():
    status, body = _request("GET", "/health/ready")
    assert status == 200, f"status {status}, body {body}"
    assert body.get("ready") is True, f"not ready: {body}"


@step("create Principal (operator key required)")
def create_principal() -> str:
    body = json.dumps({"name": "Smoke Test Principal"}).encode()
    status, resp = _request("POST", "/v1/principals", body, _operator_headers())
    assert status == 201, f"status {status}, body {resp}"
    return resp["id"]


@step("register Agent with a freshly generated ED25519 keypair")
def create_agent(principal_id: str) -> tuple[str, str, nacl.signing.SigningKey]:
    signing_key = nacl.signing.SigningKey.generate()
    public_key_b64 = base64.b64encode(bytes(signing_key.verify_key)).decode()
    body = json.dumps(
        {
            "name": "smoke-test-agent",
            "acting_for_principal_id": principal_id,
            "public_key": f"ed25519:base64:{public_key_b64}",
        }
    ).encode()
    status, resp = _request("POST", "/v1/agents", body, _operator_headers())
    assert status == 201, f"status {status}, body {resp}"
    return resp["id"], resp["certificate_id"], signing_key


@step("activate the newly registered Agent (registered -> active)")
def activate_agent(agent_id: str):
    # A freshly registered Agent's certificate starts "issued", not
    # "active" (server/app/services/agent_service.py::create_agent).
    # This explicit activation step, not certificate issuance itself, is
    # what a signed Intent's certificate check actually requires.
    status, resp = _request("POST", f"/v1/agents/{agent_id}/activate", b"{}", _operator_headers())
    assert status == 200, f"status {status}, body {resp}"


@step("submit a signed Intent and receive a real Decision")
def submit_intent(agent_id: str, certificate_id: str, signing_key: nacl.signing.SigningKey) -> tuple[str, str]:
    payload = {
        "agent_id": agent_id,
        "action": "vendor_payment",
        "amount": 1250.00,
        "currency": "USD",
        "counterparty": "Smoke Test Vendor Inc.",
        "context": {},
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "nonce": f"smoke-{time.time_ns()}",
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = base64.b64encode(signing_key.sign(body).signature).decode()
    status, resp = _request(
        "POST",
        "/v1/intents",
        body,
        {"X-PayReality-Key-Id": certificate_id, "X-PayReality-Signature": signature},
    )
    assert status == 200, f"status {status}, body {resp}"
    assert resp["decision"]["outcome"] in ("ALLOW", "DENY", "HUMAN_REVIEW"), resp
    return resp["decision"]["decision_id"], resp["evidence_id"]


@step("resolve a HUMAN_REVIEW decision if that's what came back")
def maybe_resolve(decision_id: str):
    status, resp = _request("GET", f"/v1/decisions/{decision_id}")
    assert status == 200, f"status {status}, body {resp}"
    if resp["outcome"] != "HUMAN_REVIEW" or resp["status"] == "RESOLVED":
        return
    body = json.dumps(
        {"resolution": "approved", "resolved_by": "smoke-test-script", "reason": "automated smoke test"}
    ).encode()
    status, resp = _request("POST", f"/v1/decisions/{decision_id}/resolve", body, _operator_headers())
    assert status == 200, f"status {status}, body {resp}"


@step("fetch and cryptographically verify the resulting Evidence")
def verify_evidence(evidence_id: str):
    # Both endpoints require an authenticated, org-scoped caller
    # (EVIDENCE_VIEW + get_current_organization) -- previously sent with
    # no headers at all, a pre-existing script bug unrelated to Milestone
    # 2/3 that would 401 independently of the organization header fix.
    status, resp = _request("GET", f"/v1/evidence/{evidence_id}", headers=_operator_headers())
    assert status == 200, f"status {status}, body {resp}"
    status, resp = _request("POST", f"/v1/evidence/{evidence_id}/verify", headers=_operator_headers())
    assert status == 200, f"status {status}, body {resp}"
    assert resp["valid"] is True, f"SIGNATURE DID NOT VERIFY: {resp}"


@step("confirm the public verification key is published and independently usable")
def check_verification_key():
    status, resp = _request("GET", "/v1/evidence/verification-key")
    assert status == 200, f"status {status}, body {resp}"
    assert resp.get("public_key_b64"), resp


@step("assurance counts: real agents and policies come back")
def check_assurance():
    # GET /v1/agents is now organization-scoped (Milestone 3) --
    # previously reachable with no authentication at all.
    status, agents = _request("GET", "/v1/agents", headers=_operator_headers())
    assert status == 200
    status, policies = _request("GET", "/v1/policies")
    assert status == 200
    print(f"        ({len(agents)} agent(s), {len(policies)} policy version(s) currently in this environment)")


def main():
    print(f"Running end-to-end smoke test against {BASE_URL}\n")
    if not OPERATOR_KEY:
        print("PAYREALITY_OPERATOR_KEY is not set. Operator-gated steps will fail with 401/422.")
    if not ORGANIZATION_ID:
        print(
            "PAYREALITY_ORGANIZATION_ID is not set. Org-scoped operator-gated steps will fail with "
            "400 organization_id_required_for_operator_key."
        )
    check_health()
    check_ready()
    principal_id = create_principal()
    agent_id, certificate_id, signing_key = create_agent(principal_id)
    activate_agent(agent_id)
    decision_id, evidence_id = submit_intent(agent_id, certificate_id, signing_key)
    maybe_resolve(decision_id)
    verify_evidence(evidence_id)
    check_verification_key()
    check_assurance()
    print(f"\n{len(_passed)}/{len(_passed)} stages passed. The full Runtime Authority pipeline is live and verified.")


if __name__ == "__main__":
    main()
