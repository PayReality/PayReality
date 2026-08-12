"""Batch evaluation (Runtime Policy Simulator, Phase 4): the same
isolated-package mechanism domain/compiler_v2/dry_run.py already
established and verified against real OPA (rewrite the package to a
unique, throwaway name, load it, query it, delete it) -- but loading the
bundle ONCE and querying it many times. dry_run() is deliberately
one-shot (one sample Intent per call); re-uploading and deleting the
identical Rego thousands of times for a historical-action replay would
be pure waste, not a meaningful safety difference -- the isolation comes
from the package name being unique to this run, not from re-uploading
per query. Reuses dry_run.py's own package-rewrite helper unchanged.
"""

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import httpx

from app.domain.compiler_v2.bundle_builder import PolicyBundle
from app.domain.compiler_v2.dry_run import DryRunError, _rewrite_package


@contextmanager
def loaded_bundle(bundle: PolicyBundle, opa_url: str, timeout_ms: int = 2000) -> Iterator[str]:
    """Yields the OPA data path this bundle is loaded at for the
    lifetime of the `with` block; guarantees cleanup (policy deletion)
    on the way out, exactly like dry_run()'s own finally block, just
    amortized across many queries instead of one."""
    token = f"t{uuid.uuid4().hex}"
    package_path = f"payreality.batch.{token}"
    policy_id = f"batch-{token}"
    rewritten_rego = _rewrite_package(bundle.rego_source, package_path)
    data_path = package_path.replace(".", "/")

    try:
        resp = httpx.put(
            f"{opa_url}/v1/policies/{policy_id}",
            content=rewritten_rego.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=timeout_ms / 1000,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise DryRunError(f"batch load failed: {e}") from e

    try:
        yield data_path
    finally:
        try:
            httpx.delete(f"{opa_url}/v1/policies/{policy_id}", timeout=timeout_ms / 1000)
        except httpx.HTTPError:
            # Best-effort cleanup, same posture as dry_run.py's own
            # finally block: an orphaned throwaway package under
            # payreality.batch.* never affects real traffic, since
            # nothing queries that path except this module.
            pass


def query_loaded_bundle(
    opa_url: str, data_path: str, input_doc: dict[str, Any], timeout_ms: int = 2000
) -> dict[str, Any]:
    try:
        resp = httpx.post(
            f"{opa_url}/v1/data/{data_path}", json={"input": input_doc}, timeout=timeout_ms / 1000
        )
        resp.raise_for_status()
        return resp.json().get("result", {})
    except httpx.HTTPError as e:
        raise DryRunError(f"batch query failed: {e}") from e
