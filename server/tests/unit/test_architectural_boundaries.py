"""Runtime Governance Architecture, Phase 2 (Dependency Intelligence):
automated conformance checks for the boundaries declared in
SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md.

Each test below corresponds to exactly one declared rule in that
document's section 26.4. These checks were previously enforced only in
running code (or by convention) with zero test coverage -- confirmed
before writing this file (no existing test referenced
UnexpectedActiveWriterError, 410, or _RETIRED_DETAIL anywhere). This file
closes that coverage gap. It does not change any enforcement itself.

The two import-boundary tests use only the standard library `ast` module,
deliberately -- this codebase has a small, shallow third-party dependency
set by design (SPECIFICATION/18_DEPENDENCY_GRAPH.md section 18.1), and
introducing a linting tool (e.g. import-linter) for two specific rules
would be a heavier footprint than "automated conformance checks where
practical" calls for.
"""

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.domain.decision import engine as decision_engine
from app.routers import policies as policies_router
from app.services.runtime_policy_service import _is_unexpected_active_writer

_APP_ROOT = Path(inspect.getfile(decision_engine)).resolve().parents[2]
_DOMAIN_ROOT = _APP_ROOT / "domain"


def _imported_module_names(source_path: Path) -> set[str]:
    """All top-level module paths a file imports, as dotted strings --
    "app.db.session" for `from app.db.session import get_db`, "app.db"
    for `from app.db import models` or `import app.db`."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _forbidden_prefixes_hit(module_names: set[str], forbidden_prefixes: tuple[str, ...]) -> set[str]:
    return {
        name
        for name in module_names
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    }


# --- Declared rule 26.4.1: Runtime Authority is pure -----------------------


def test_decision_engine_imports_nothing_from_db_services_or_routers():
    """domain/decision/engine.py must remain testable without a database
    and structurally incapable of reaching Policy Intelligence's,
    Context's, or Decision Evidence's implementations directly -- it may
    only know them through the OpaClient/PolicyStore Protocols its caller
    supplies. Verified today: its only imports are `dataclasses` and
    `typing`. This test fails the moment that stops being true."""
    engine_path = Path(inspect.getfile(decision_engine))
    imports = _imported_module_names(engine_path)
    hits = _forbidden_prefixes_hit(imports, ("app.db", "app.services", "app.routers"))
    assert not hits, (
        f"domain/decision/engine.py imports from a forbidden package: {hits}. "
        "Runtime Authority must remain pure -- see "
        "SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md section 26.4.1."
    )


# --- Declared rule 26.4.2: domain/ never touches app.db ---------------------


def test_domain_package_never_imports_app_db():
    """The whole domain/ package, not just engine.py: pure business logic
    with no database access anywhere, verified by walking every .py file
    under domain/. Zero hits today (confirmed by direct grep before
    writing this test) -- declared here as a permanent constraint, not an
    accident of current convenience."""
    violations: dict[str, set[str]] = {}
    for path in _DOMAIN_ROOT.rglob("*.py"):
        imports = _imported_module_names(path)
        hits = _forbidden_prefixes_hit(imports, ("app.db",))
        if hits:
            violations[str(path.relative_to(_APP_ROOT.parent))] = hits
    assert not violations, (
        f"domain/ modules importing app.db, which must stay service-layer-only: {violations}. "
        "See SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md section 26.4.2."
    )


# --- Declared rule 26.4.3: single writer to the active Policy row ----------


class _FakePolicyRow:
    def __init__(self, bundle_uri: str):
        self.bundle_uri = bundle_uri


def test_no_prior_active_policy_is_not_an_unexpected_writer():
    """First-ever deploy: nothing active yet, nothing to conflict with."""
    assert _is_unexpected_active_writer(None) is False


def test_prior_active_written_by_deploy_policy_is_not_unexpected():
    """The expected, sole-writer case: deploy_policy retiring its own
    previously-deployed bundle."""
    prior = _FakePolicyRow(bundle_uri="runtime_policy_studio:some-key:3")
    assert _is_unexpected_active_writer(prior) is False


def test_prior_active_written_by_anything_else_is_rejected():
    """The single-writer guarantee itself: any active Policy row whose
    bundle_uri doesn't match this module's own format was written by some
    other, undeclared path -- deploy_policy must refuse to silently
    overwrite it. This is the exact scenario the legacy Authority/Mandate
    pipeline used to create before its write endpoints were retired
    (SPECIFICATION/17_LEGACY_COMPONENTS.md), and the exact scenario any
    future undeclared writer would also trigger."""
    prior = _FakePolicyRow(bundle_uri="legacy_pipeline:some-other-format")
    assert _is_unexpected_active_writer(prior) is True


# --- Declared rule 26.4.4: legacy write endpoints stay retired --------------


@pytest.mark.parametrize(
    "endpoint_name,call_kwargs",
    [
        ("upload_document", {"file": None, "db": None}),
        ("review_authority", {"authority_id": None, "body": None, "db": None}),
        ("compile_policy", {"document_id": None, "db": None}),
        ("activate_policy", {"policy_id": None, "db": None}),
    ],
)
async def test_legacy_policy_write_endpoints_remain_retired(endpoint_name, call_kwargs):
    """All four legacy write endpoints on routers/policies.py raise 410
    before touching either of their arguments (confirmed by reading each
    function body: the raise is the only statement) -- so calling them
    directly with None/dummy arguments, bypassing FastAPI's dependency
    injection entirely, exercises the real, complete behavior. This
    codebase has no existing TestClient-based router test pattern
    (confirmed before writing this file); introducing one just for this
    check would be a heavier footprint than this phase's own "avoid
    changing runtime behavior... where practical" scope calls for.

    A regression here would silently reopen the two-OPA-writer risk
    Phase 0 already retired -- see
    SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md section 26.4.4."""
    endpoint = getattr(policies_router, endpoint_name)
    with pytest.raises(HTTPException) as exc_info:
        result = endpoint(**call_kwargs)
        if inspect.isawaitable(result):
            await result
    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == policies_router._RETIRED_DETAIL
