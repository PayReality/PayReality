"""httpx-based OPA client: implements the OpaClient protocol used by
app.domain.decision.engine, and the bundle-activation calls used by the
Policy Compiler (spec 12.4 Stage 9).

Milestone 2 (Multi-Tenant Foundation,
MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md Phase B1/B2, Option 2):
before this milestone, every organization shared exactly one OPA
package, `payreality.authorization`, uploaded and queried via the
literal `DATA_PATH` constant below. Every organization now compiles to,
and is queried against, its own package,
`payreality.authorization.org_<hex>` -- the three naming helpers below
are the single place that name is computed, reused by both
runtime_policy_service.py (compile/deploy/reconcile) and
intent_service.py (the live decision path), so the two can never
independently drift on what an organization's package is actually
called. `DATA_PATH` itself is kept as the pre-Milestone-2 default for
any caller that hasn't been updated to pass an explicit path -- there
should be none left after this milestone's remaining commits, but
`query()` fails loudly (a 404-shaped OPA response, not a silent
cross-tenant read) rather than guessing if one is ever missed."""

import threading
import uuid
from typing import Any

import httpx

from app.config import settings
from app.domain.decision.engine import OPAEvaluationError, OPATimeoutError

DATA_PATH = "/v1/data/payreality/authorization"

# Root-cause fix (postgres-and-opa-fixes pass): THE actual, primary
# cause of the OPA ReadTimeout failures under investigation. Directly
# measured, not assumed: httpx.Client() construction itself took
# 0.6-0.9s on the machine this was diagnosed on (almost certainly
# Windows' own system proxy auto-detection, which httpx/httpcore
# perform once per Client instance) -- a raw socket doing the identical
# request completed in 2-9ms, and a REUSED httpx.Client completed the
# same request in 2-4ms on every call after the first. Every method
# below previously called the module-level httpx.get/post/put/delete
# convenience functions, each of which constructs and discards a brand
# new httpx.Client internally -- so EVERY single OPA request, from any
# caller anywhere in this codebase, paid that full ~0.6-0.9s client-
# construction tax before the actual (fast) network round trip even
# began. Critically, this construction cost occurs *before* httpx's own
# per-request timeout clock starts, so it was completely invisible to
# `timeout=` -- explaining directly why even a deliberately tiny 10ms
# timeout in isolated testing never once fired despite 500ms-900ms of
# real elapsed time.
#
# Fixed with one process-wide, lazily-constructed, shared httpx.Client
# -- HttpOpaClient itself stays cheap to construct per call site (the
# existing pattern throughout this codebase), but the expensive
# underlying transport is paid for exactly once per process lifetime,
# not once per request. A per-request full URL is still used (never a
# fixed base_url on the shared client), since different HttpOpaClient
# instances legitimately point at different OPA hosts (e.g. per test).
_shared_client_lock = threading.Lock()
_shared_client: httpx.Client | None = None


def _get_shared_client() -> httpx.Client:
    global _shared_client
    if _shared_client is None:
        with _shared_client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client()
    return _shared_client


def org_package_path(organization_id: uuid.UUID) -> str:
    """The Rego package name for one organization's compiled bundle.
    `.hex` (not the dashed string form) because a Rego package path
    segment must be a valid identifier -- no hyphens -- the same
    constraint dry_run.py's own package-naming already has to respect."""
    return f"payreality.authorization.org_{organization_id.hex}"


def org_data_path(organization_id: uuid.UUID) -> str:
    """The `/v1/data/...` path OPA serves that package's rules at --
    always the package path with dots replaced by slashes, OPA's own
    fixed convention, the same one dry_run.py/batch_evaluator.py already
    rely on for their own throwaway packages."""
    return "/v1/data/" + org_package_path(organization_id).replace(".", "/")


def org_policy_id(organization_id: uuid.UUID) -> str:
    """The OPA REST policy id (`PUT /v1/policies/<id>`) one
    organization's compiled bundle is uploaded under -- a plain resource
    id, not a Rego identifier, so hyphens are fine here unlike the
    package path above."""
    return f"authorization-org-{organization_id.hex}"


class HttpOpaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.opa_url

    def query(
        self, input_doc: dict[str, Any], timeout_ms: int = 200, data_path: str | None = None
    ) -> dict[str, Any]:
        # Root-cause fix (postgres-and-opa-fixes pass): a bare float
        # passed as httpx's `timeout` sets FOUR INDEPENDENT sub-budgets
        # (connect, write, read, pool) to that SAME value -- it is not a
        # single overall deadline (confirmed directly: httpx.Timeout(0.2)
        # reports connect=0.2, read=0.2, write=0.2, pool=0.2). A caller
        # of this function, and decision_engine.evaluate's own fail-
        # closed contract, both expect timeout_ms to bound the REAL,
        # total wall-clock time before a decision either returns or
        # fails closed to HUMAN_REVIEW -- not to allow each phase up to
        # timeout_ms separately, which can silently stack to roughly 4x
        # the intended budget before anything actually times out. This
        # was directly measured, not assumed: a bounded, reproducible
        # load experiment against a real `opa` binary observed real
        # round-trip latencies of 400ms-2.2s under `timeout_ms=200`
        # with ZERO of the four independent sub-budgets ever
        # individually exceeded, so OPATimeoutError never fired even
        # though every single one of those requests took 2-10x longer
        # than the intended decision-latency budget.
        #
        # Fix: split the caller's single intended budget across the
        # four phases rather than repeating it at each one. For OPA's
        # real, documented, intended deployment shape (a co-located
        # sidecar or same-host process -- every architecture reference
        # in this codebase assumes this), connect/write/pool are near-
        # zero in a healthy deployment; giving each of those three a
        # smaller, fixed share and reserving the rest for the actual
        # rule evaluation (`read`) keeps the common case unaffected
        # while making the WORST case (every phase maxing its own
        # share) sum to no more than the caller's own timeout_ms,
        # exactly as already promised.
        total_s = timeout_ms / 1000
        # Three auxiliary phases (connect, write, pool) each get a
        # small, fixed-proportion share; `read` gets whatever remains,
        # so the WORST case (all four phases individually maxing their
        # own share) sums to exactly total_s, never more -- the
        # arithmetic that actually matters here, checked directly:
        # 3 * auxiliary_s + read_s == total_s.
        auxiliary_s = min(total_s / 10, 0.05)
        read_s = total_s - 3 * auxiliary_s
        request_timeout = httpx.Timeout(
            read_s, connect=auxiliary_s, write=auxiliary_s, pool=auxiliary_s,
        )
        try:
            resp = _get_shared_client().post(
                f"{self.base_url}{data_path or DATA_PATH}",
                json={"input": input_doc},
                timeout=request_timeout,
            )
        except httpx.TimeoutException as e:
            raise OPATimeoutError() from e
        except httpx.HTTPError as e:
            raise OPAEvaluationError(code="connection_error", message=str(e)) from e

        if resp.status_code != 200:
            raise OPAEvaluationError(code=f"http_{resp.status_code}")

        try:
            body = resp.json()
        except ValueError as e:
            raise OPAEvaluationError(code="bad_response") from e

        result = body.get("result")
        if result is None:
            # OPA returns no "result" key when the queried path is undefined.
            return {}
        return result

    def upload_data(self, path: str, data: Any) -> None:
        """PUT arbitrary data (e.g. compiled mandates/constraints) into
        OPA's in-memory data store at data.<path>."""
        resp = _get_shared_client().put(f"{self.base_url}/v1/data/{path}", json=data, timeout=5.0)
        resp.raise_for_status()

    def upload_policy(self, policy_path: str, rego_source: str) -> str:
        """PUT a Rego module, returns the revision OPA assigns."""
        resp = _get_shared_client().put(
            f"{self.base_url}/v1/policies/{policy_path}",
            content=rego_source.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return resp.json().get("result", {}).get("revision", "")

    def delete_policy(self, policy_path: str) -> None:
        """DELETE a Rego module (standard OPA REST API, `DELETE /v1/
        policies/<id>`). PayReality 1.0 Audit finding G02 (verification-
        closure pass): the missing half of upload_policy -- reconciling
        OPA to "this organization now has zero active RuntimePolicy"
        requires actually removing what's there, not merely declining to
        push anything new (which silently leaves stale, possibly never-
        committed rego live and enforceable). A 404 (nothing was loaded
        under this id) is treated as already-consistent, not an error --
        the caller's intent is "make sure this id isn't serving stale
        content," which is already true either way."""
        resp = _get_shared_client().delete(f"{self.base_url}/v1/policies/{policy_path}", timeout=5.0)
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    def health(self) -> bool:
        try:
            resp = _get_shared_client().get(f"{self.base_url}/health", timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
