"""Decision Intelligence HTTP surface -- one sub-package, one module per
sub-resource (workflows/cases/patterns/questions/answers/rules/replays/
imports/reports/scoring_config), matching this codebase's own single-
file-per-feature router convention scaled up for a module with this many
sub-resources. Every router below lives under the shared
/v1/decision-intelligence prefix; see app.main's include_router calls for
how they're wired in. The settings module is named `scoring_config`, not
`settings`, deliberately -- to avoid any reader confusion with
`app.config.settings` (the application-wide settings object), an
unrelated and much more commonly imported name in this codebase."""

from app.routers.decision_intelligence import (
    answers,
    cases,
    imports,
    patterns,
    questions,
    replays,
    reports,
    rules,
    scoring_config,
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
    "scoring_config",
    "workflows",
]
