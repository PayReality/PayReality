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

import uuid
from typing import Any

import httpx

from app.config import settings
from app.domain.decision.engine import OPAEvaluationError, OPATimeoutError

DATA_PATH = "/v1/data/payreality/authorization"


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
        try:
            resp = httpx.post(
                f"{self.base_url}{data_path or DATA_PATH}",
                json={"input": input_doc},
                timeout=timeout_ms / 1000,
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
        resp = httpx.put(f"{self.base_url}/v1/data/{path}", json=data, timeout=5.0)
        resp.raise_for_status()

    def upload_policy(self, policy_path: str, rego_source: str) -> str:
        """PUT a Rego module, returns the revision OPA assigns."""
        resp = httpx.put(
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
        resp = httpx.delete(f"{self.base_url}/v1/policies/{policy_path}", timeout=5.0)
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    def health(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/health", timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
