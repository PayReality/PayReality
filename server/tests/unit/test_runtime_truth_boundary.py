"""Runtime Governance Architecture, Phase 5 (45_PHASE_5_BROKEN_PROMISE_REPORT.md):
Runtime Truth Separation is one of this architecture's named promises --
resolving what is true must never depend on evaluating whether it's
permitted. Phase 2 (test_architectural_boundaries.py) already made the
complementary half of this guarantee continuously verifiable: Runtime
Authority (domain/decision/engine.py) cannot import Runtime Truth's
implementation. That test says nothing about the other direction --
whether Runtime Truth could grow a dependency back onto the evaluation
engine it feeds. It doesn't today (confirmed before writing this file:
runtime_truth_service.py's only imports are dataclasses, sqlalchemy, and
app.db.models/app.services.authority_context_service), but nothing
before this test made that a continuously-checked fact rather than
something true only by inspection.

Same technique as Phase 2's existing checks (stdlib `ast`, no new
dependency), placed in its own file rather than added to Phase 2's
test_architectural_boundaries.py so this phase's addition is not
mistaken for a modification of a previous phase's own deliverable.
"""

import ast
import inspect
from pathlib import Path

from app.services import runtime_truth_service


def _imported_module_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_runtime_truth_service_never_imports_the_decision_engine():
    """Resolution must stay independent of evaluation -- Runtime Truth
    composes Principal Directory and Runtime Context Service lookups
    only (29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md); it must never reach
    into domain.decision, the module it hands its result to. This is the
    other half of the non-dependency Phase 2 already tests from
    decision_engine's side."""
    source_path = Path(inspect.getfile(runtime_truth_service))
    imports = _imported_module_names(source_path)
    forbidden = {"app.domain.decision", "app.routers"}
    hits = {
        name
        for name in imports
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    }
    assert not hits, (
        f"runtime_truth_service.py imports from a forbidden package: {hits}. "
        "Runtime Truth must stay independent of Runtime Authority's evaluation -- "
        "see SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md."
    )
