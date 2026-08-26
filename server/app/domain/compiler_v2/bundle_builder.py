"""Assembles the compiled Rego rules for a set of RuntimePolicies into one
Policy Bundle: a complete Rego module plus the metadata
(AUTHORING_ARCHITECTURE.md calls the compiled, versioned, activatable
unit a "Policy Bundle" to distinguish it from a single RuntimePolicy).

Output field names deliberately match what domain/decision/engine.py
already reads today (`allow`, `deny`, `requires_review`,
`evaluated_mandates`, `review_reason`, `deny_reason`): "the Runtime
Authority Engine must never know where a policy came from" only holds if
this bundle's output shape is what the *unmodified* engine already
expects. Reusing `evaluated_mandates` here, rather than a more accurate
name, is a deliberate compatibility choice: renaming it is a real
future improvement, but it's engine.py's name to change, and engine.py
is explicitly out of scope for this phase. See
tests/test_compiler_v2_opa_integration.py, which runs a compiled bundle
through the actual, unmodified evaluate() function to prove this
compatibility claim rather than just assert it.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domain.runtime_policy.runtime_policy import RuntimePolicy

from app.domain.compiler_v2.rego_generator import (
    effect_rule_name,
    generate_policy_rule,
    rule_name_for_policy,
)

COMPILER_VERSION = "2.0.0"

_PACKAGE_LINE_PATTERN = re.compile(r"^package\s+\S+", re.MULTILINE)


class PackageRetargetError(Exception):
    """Raised only if `rego_source` has no `package` declaration to
    rewrite at all -- a genuine programming error (every bundle this
    module produces always has one, per build_bundle's own
    `rego_source` assembly), never a normal outcome."""


def retarget_package(rego_source: str, package_path: str) -> str:
    """Rewrites a compiled bundle's `package` declaration to
    `package_path`, leaving every rule body untouched. Every bundle this
    module builds hardcodes `package payreality.authorization`
    (build_bundle, below) -- this is the one, single place that name is
    ever changed, reused by both dry_run.py's throwaway-package
    isolation mechanism and, from Milestone 2 (Multi-Tenant Foundation)
    onward, runtime_policy_service's per-organization OPA packages
    (`payreality.authorization.org_<hex>`). Extracted here, out of
    dry_run.py's own private copy, specifically because it now has two
    genuinely independent callers rather than one -- promoted to public
    (no leading underscore) for exactly that reason, the same
    cross-module-reuse convention already established for
    organization_structure_service's org-resolution helpers.

    Verified directly against a real local OPA server (dry_run.py's own
    docstring): rewriting the package line and re-uploading under a
    distinct policy id is OPA's normal policy-loading mechanism, not a
    special API -- isolation comes entirely from the distinct package
    name."""
    replacement = f"package {package_path}"
    new_source, count = _PACKAGE_LINE_PATTERN.subn(replacement, rego_source, count=1)
    if count == 0:
        raise PackageRetargetError("rego source has no package declaration to rewrite")
    return new_source


@dataclass(frozen=True)
class PolicyBundle:
    bundle_id: str
    version: int
    runtime_policy_ids: tuple[str, ...]
    compiler_version: str
    bundle_hash: str
    rego_source: str
    manifest: dict[str, Any]


def _canonical_bytes(rego_source: str, manifest: dict[str, Any]) -> bytes:
    """Same discipline as domain/compiler/compiler.py's _canonical_bytes:
    sorted keys, no incidental whitespace, so compiling the identical
    RuntimePolicy set twice produces a byte-identical bundle_hash."""
    payload = {"rego": rego_source, "manifest": manifest}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_bundle(
    policies: list[RuntimePolicy],
    bundle_id: str,
    bundle_version: int,
    now: datetime | None = None,
) -> PolicyBundle:
    """Assumes every policy in `policies` has already passed validation
    (runtime_policy.validators.validate() plus compiler_v2.py's own
    compile-time checks); this function does not re-validate, it only
    assembles. Callers (compiler_v2.py) are responsible for only ever
    calling this with policies that passed."""
    now = now or datetime.now(timezone.utc)

    policy_rules = [generate_policy_rule(p) for p in policies]

    by_effect: dict[str, list[str]] = {"allow": [], "deny": [], "requires_review": []}
    for policy in policies:
        rule_name = rule_name_for_policy(policy.id)
        by_effect[effect_rule_name(policy.effect)].append(rule_name)

    aggregate_lines: list[str] = []
    for outcome_name, rule_names in by_effect.items():
        for rn in rule_names:
            aggregate_lines.append(f"{outcome_name} if {{ {rn} }}")

    evaluated_lines = [
        f'evaluated_mandates contains {json.dumps(policy.id)} if {{ {rule_name_for_policy(policy.id)} }}'
        for policy in policies
    ]

    reason_lines: list[str] = []
    for policy in policies:
        rn = rule_name_for_policy(policy.id)
        if policy.effect.value == "require_human_review":
            reason_lines.append(
                f'review_reason := {json.dumps("policy_matched:" + policy.id)} if {{ {rn} }}'
            )
        elif policy.effect.value == "deny":
            reason_lines.append(
                f'deny_reason := {json.dumps("policy_matched:" + policy.id)} if {{ {rn} }}'
            )

    # Fail-closed fallback, generalizing domain/compiler/compiler.py's
    # existing "deny if count(matching_mandate) == 0" behavior: if no
    # RuntimePolicy's scope and conditions matched at all, that is itself
    # a deny, not silence. evaluated_mandates covers every policy whose
    # match succeeded regardless of its own effect, so "empty" genuinely
    # means "nothing in this bundle applies to this Intent."
    fallback_lines = [
        "deny if { count(evaluated_mandates) == 0 }",
        'deny_reason := "no_policy_covers_scope" if { count(evaluated_mandates) == 0 }',
    ]

    rego_source = "\n\n".join(
        [
            "package payreality.authorization",
            "\n".join(
                [
                    "default allow := false",
                    "default deny := false",
                    "default requires_review := false",
                ]
            ),
            "\n\n".join(policy_rules) if policy_rules else "# no RuntimePolicies in this bundle",
            "\n".join(aggregate_lines) if aggregate_lines else "# no effect rules to aggregate",
            "\n".join(evaluated_lines) if evaluated_lines else "# no policies evaluated",
            "\n".join(reason_lines) if reason_lines else "# no deny/review reasons declared",
            "\n".join(fallback_lines),
        ]
    )

    manifest = {
        "bundle_id": bundle_id,
        "version": bundle_version,
        "compiler_version": COMPILER_VERSION,
        "compiled_at": now.isoformat(),
        "policies": [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "effect": p.effect.value,
                "scope": {
                    "principal": p.scope.principal,
                    "action": p.scope.action,
                    "agent": p.scope.agent,
                    "resource": p.scope.resource,
                },
                # Authority Graph -> RuntimePolicy Compilation Gate
                # (issue #6): only present for a graph-derived policy
                # (p.metadata.source_type set) -- omitted entirely for a
                # manually-authored or standalone-candidate policy, never
                # present-but-null, so this manifest entry's shape stays
                # exactly what every existing reader already expects
                # unless a policy is actually graph-derived. This is
                # what makes the source graph version survive into
                # Policy.bundle_manifest and, from there, into a
                # historical Decision's own bound Policy row and the
                # Authorization Receipt (PolicyManifestEntry reused
                # unchanged by both).
                **(
                    {
                        "source": {
                            "type": p.metadata.source_type,
                            "corpus_id": p.metadata.source_corpus_id,
                            "graph_approval_id": p.metadata.source_graph_approval_id,
                            "graph_version": p.metadata.source_graph_version,
                            "candidate_id": p.metadata.source_candidate_id,
                        }
                    }
                    if p.metadata.source_type
                    else {}
                ),
            }
            for p in policies
        ],
    }

    # compiled_at is deliberately excluded from what gets hashed: it's a
    # wall-clock timestamp, so including it would mean recompiling the
    # exact same set of policies a second later always produces a
    # different bundle_hash, which is exactly the bug that made
    # deploy_policy's staleness check (bundle_hash != row.bundle_hash)
    # fail every single time, not just when something had genuinely
    # changed. The legacy compiler (domain/compiler/compiler.py) never
    # had this problem since its hash input never included a timestamp;
    # this restores the same "identical input -> identical hash"
    # guarantee this module's own docstring already claims.
    hashable_manifest = {k: v for k, v in manifest.items() if k != "compiled_at"}
    bundle_hash = "sha256:" + hashlib.sha256(_canonical_bytes(rego_source, hashable_manifest)).hexdigest()

    return PolicyBundle(
        bundle_id=bundle_id,
        version=bundle_version,
        runtime_policy_ids=tuple(p.id for p in policies),
        compiler_version=COMPILER_VERSION,
        bundle_hash=bundle_hash,
        rego_source=rego_source,
        manifest=manifest,
    )
