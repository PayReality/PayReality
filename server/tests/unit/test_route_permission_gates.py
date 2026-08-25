"""Milestone 15 (real-session RBAC verification): a live probe against
production found that every GET on /v1/runtime-policies (list, detail,
versions, version diff) plus its dry-run simulation action had ZERO
permission gate at all -- any authenticated user, any role, including
EXECUTIVE (whose entire defined scope is assurance.view), could read and
simulate an organization's complete policy library. A follow-up source
sweep found the same class of gap across /v1/agents/{id} and its
certificate/audit sub-resources, and across most of the AI Authority
Builder's and AI Policy Builder's read endpoints -- in every case, the
route's LIST endpoint or its WRITE actions were correctly gated with
require_permission, but a DETAIL or sub-resource GET endpoint for the
same resource was not.

This escaped 428 passing tests because this codebase's own established
convention (RBAC.md; see test_policy_api_security.py and
test_rbac_permissions.py) is to call `require_permission(permission)`'s
returned checker directly, never through a real HTTP request. That
convention proves the checker's LOGIC is correct in isolation; it can
never prove a given ROUTE actually attached that checker as a
dependency. This file closes that specific, structural blind spot for
every current and future route in one place, by introspecting the real
FastAPI route table instead of calling permission logic by hand.

This test does not replace the direct-call convention (still the right
tool for testing what a permission decision resolves to); it adds the
one thing that convention structurally cannot check: that the checker
is actually wired to the route serving real data.
"""

from fastapi.routing import APIRoute

from app.main import app

# Every route below is deliberately reachable without require_permission/
# verify_operator_key, each for a stated, reviewed reason. Adding a route
# to this set must be a deliberate decision, not a way to silence this
# test -- a new entry with no real justification is exactly the mistake
# this file exists to catch.
ALLOWED_UNGATED = {
    ("POST", "/v1/auth/login"): "unauthenticated by necessity -- this IS how a session is obtained",
    ("POST", "/v1/auth/logout"): "must succeed even with an already-expired/invalid session token",
    ("GET", "/v1/auth/me"): "gated by get_current_user (a real session-required auth dependency, just not a specific Permission)",
    ("POST", "/v1/auth/accept-invitation"): "unauthenticated by necessity -- a new member holds only a one-time invitation token, not a session yet",
    ("POST", "/v1/intents"): "gated by verify_agent_signature -- a real, different auth mechanism (Ed25519 request signature) for machine-to-machine calls, not a human role",
    ("POST", "/v1/agents/{agent_id}/heartbeat"): "gated by verify_agent_signature, same reason as POST /v1/intents",
    ("GET", "/v1/evidence/verification-key"): "deliberately public by design (EVIDENCE_KEY_ROTATION.md) -- a regulator/insurer/auditor must be able to verify a signature independently of trusting this API",
    ("GET", "/v1/evidence/verification-keys"): "same deliberate public-verification design as /v1/evidence/verification-key",
    ("GET", "/v1/runtime-policies/vocabulary"): "a fixed, non-organization-scoped reference vocabulary (known action names), no tenant data returned",
    ("GET", "/v1/ai-policy-builder/status"): "returns only a global ai_enabled boolean, no organization-scoped data",
    ("GET", "/v1/ai-authority-builder/status"): "returns only a global ai_enabled boolean, no organization-scoped data",
    ("POST", "/v1/facts"): "authenticated by the fact's own Ed25519 signature against its registered FactSource, the same machine-to-machine model as POST /v1/intents -- deliberately never trusts the requesting agent's own RBAC role or session to self-attest an external fact",
}


def _all_api_routes(routes):
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from _all_api_routes(route.original_router.routes)
        elif isinstance(route, APIRoute):
            yield route


def _is_gated(route: APIRoute) -> bool:
    for dependency in route.dependant.dependencies:
        qualname = getattr(dependency.call, "__qualname__", "")
        name = getattr(dependency.call, "__name__", "")
        if "require_permission" in qualname or name == "verify_operator_key":
            return True
    return False


def test_every_v1_route_is_permission_gated_or_explicitly_justified():
    ungated_and_unexplained = []
    for route in _all_api_routes(app.routes):
        if not route.path.startswith("/v1/"):
            continue
        if _is_gated(route):
            continue
        methods = sorted(m for m in route.methods if m != "HEAD")
        for method in methods:
            if (method, route.path) not in ALLOWED_UNGATED:
                ungated_and_unexplained.append(f"{method} {route.path}")

    assert not ungated_and_unexplained, (
        "Route(s) with no require_permission/verify_operator_key dependency "
        "and no entry in ALLOWED_UNGATED (server/tests/unit/"
        "test_route_permission_gates.py): "
        f"{ungated_and_unexplained}. Either add the missing "
        "dependencies=[Depends(require_permission(Permission.X))] to the "
        "route, or add a reviewed, justified entry to ALLOWED_UNGATED if "
        "it is genuinely meant to be reachable without one."
    )


def test_allowed_ungated_entries_still_correspond_to_a_real_route():
    """Catches the inverse mistake: an ALLOWED_UNGATED entry surviving
    after its route was deleted or its path changed, silently losing its
    protective value without anyone noticing."""
    real_routes = set()
    for route in _all_api_routes(app.routes):
        if not route.path.startswith("/v1/"):
            continue
        for method in route.methods:
            if method != "HEAD":
                real_routes.add((method, route.path))

    stale_entries = [key for key in ALLOWED_UNGATED if key not in real_routes]
    assert not stale_entries, f"ALLOWED_UNGATED entries with no matching live route: {stale_entries}"
