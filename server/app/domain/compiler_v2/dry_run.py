"""Dry-run evaluation of a compiled-but-not-active PolicyBundle against a
sample Intent, guaranteed to never affect the live active bundle.

The mechanism, verified directly against a real local OPA 1.7.1 server
before being relied on here (an earlier design sketch in
POLICY_COMPILER_V2.md assumed OPA's ad hoc query endpoint accepts an
inline data/policy override; it does not, and this module reflects the
mechanism that was actually confirmed to work, not the original guess):

1. Rewrite the candidate bundle's Rego source so its `package` declaration
   is a unique, throwaway name (payreality.dryrun.<token>), never
   `payreality.authorization` (the live package real traffic reads).
2. PUT it to OPA under a unique policy id. This *is* OPA's normal
   policy-loading mechanism (the same one HttpOpaClient.upload_policy
   already uses for the live bundle); the isolation comes entirely from
   the distinct package name, not from a different API. Verified
   directly: loading a second package alongside a "live" one, querying
   both, and confirming a query against the live package's path is
   completely unaffected by whatever the throwaway package contains.
3. Query the throwaway package's own data path with the sample input.
4. Delete the throwaway policy in a `finally` block, so dry-runs never
   accumulate in OPA's loaded policy set. Verified: after deletion, the
   throwaway path returns nothing, and the live package is unaffected
   throughout.
"""

import uuid
from dataclasses import dataclass

import httpx

from app.domain.compiler_v2.bundle_builder import PackageRetargetError, PolicyBundle, retarget_package


class DryRunError(Exception):
    """Raised only for an infrastructure failure (OPA unreachable, a
    timeout, a malformed response). A sample Intent resulting in deny or
    requires_review is a normal, valid dry-run outcome, never an error."""


@dataclass(frozen=True)
class DryRunResult:
    allow: bool
    deny: bool
    requires_review: bool
    evaluated_mandates: list[str]
    review_reason: str | None
    deny_reason: str | None


def dry_run(
    bundle: PolicyBundle,
    sample_input: dict,
    opa_url: str = "http://localhost:8181",
    timeout_ms: int = 2000,
) -> DryRunResult:
    # "t" prefix is required, not decorative: a Rego package path segment
    # must not start with a digit, and uuid4().hex can (verified directly
    # against real OPA: "package payreality.dryrun.823b57d0..." fails to
    # parse with "illegal number format", since Rego reads a
    # leading-digit segment as a malformed number literal, not an
    # identifier).
    token = f"t{uuid.uuid4().hex}"
    package_path = f"payreality.dryrun.{token}"
    policy_id = f"dryrun-{token}"
    try:
        rewritten_rego = retarget_package(bundle.rego_source, package_path)
    except PackageRetargetError as e:
        raise DryRunError(str(e)) from e
    data_path = package_path.replace(".", "/")

    try:
        put_resp = httpx.put(
            f"{opa_url}/v1/policies/{policy_id}",
            content=rewritten_rego.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=timeout_ms / 1000,
        )
        put_resp.raise_for_status()

        query_resp = httpx.post(
            f"{opa_url}/v1/data/{data_path}",
            json={"input": sample_input},
            timeout=timeout_ms / 1000,
        )
        query_resp.raise_for_status()
        result = query_resp.json().get("result", {})

        return DryRunResult(
            allow=result.get("allow", False),
            deny=result.get("deny", False),
            requires_review=result.get("requires_review", False),
            evaluated_mandates=list(result.get("evaluated_mandates", [])),
            review_reason=result.get("review_reason"),
            deny_reason=result.get("deny_reason"),
        )
    except httpx.HTTPError as e:
        raise DryRunError(f"dry-run evaluation failed: {e}") from e
    finally:
        try:
            httpx.delete(f"{opa_url}/v1/policies/{policy_id}", timeout=timeout_ms / 1000)
        except httpx.HTTPError:
            # Best-effort cleanup: a failed delete leaves one orphaned,
            # harmlessly-named throwaway package in OPA's loaded policy
            # set, never something that could affect real traffic (it's
            # not `payreality.authorization`, and nothing ever queries a
            # dryrun.* path except this function). Not re-raised, since
            # the actual dry-run result (or its real failure) already
            # happened above and matters more than cleanup succeeding.
            pass
