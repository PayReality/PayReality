"""Decision Intelligence HTTP surface -- one sub-package, one module per
sub-resource (workflows/cases/patterns/questions/answers/rules/replays/
imports/reports), matching this codebase's own single-file-per-feature
router convention scaled up for a module with this many sub-resources.
Every router below lives under the shared /v1/decision-intelligence
prefix; see app.main's include_router calls for how they're wired in."""

from app.routers.decision_intelligence import (
    answers,
    cases,
    imports,
    patterns,
    questions,
    replays,
    reports,
    rules,
    workflows,
)

__all__ = [
    "answers",
    "cases",
    "imports",
    "patterns",
    "questions",
    "replays",
    "reports",
    "rules",
    "workflows",
]
