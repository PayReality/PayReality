"""Decision provenance (Product Experience Remediation Milestone 1).

Self-declared by the caller at submission time, not cryptographically
provable: the Ed25519 signature over an Intent proves the private key
holder's identity, never *what process* held that key at the moment of
signing. The manual "Test Decision" UI (LiveTestIntent.tsx) signs with
the same real agent private key a genuine SDK integration would --
that's the whole point of it, proving the pipeline with a real
signature -- so the server has no signal beyond the caller's own word
for which of the two this was. This module exists to be honest about
that limit, not to paper over it.

Only two real, distinguishable callers exist today, so only two values
exist:

- SOURCE_RUNTIME: the default. Any submission that doesn't explicitly
  claim otherwise -- in practice, every real SDK integration, which has
  no reason to ever set this field at all.
- SOURCE_MANUAL_TEST: explicitly and only ever sent by the manual
  submission form itself.

A *policy simulation* (Policy Studio's dry-run, the standalone Runtime
Policy Simulator) is a third, genuinely different thing -- it evaluates
a hypothetical input directly against OPA and never creates an Intent,
Decision, or Evidence row at all (see runtime_policy_service.dry_run_policy
and policy_simulation_service.simulate). It intentionally has no value
here, because there is nothing in this table for it to tag.
"""

SOURCE_RUNTIME = "runtime"
SOURCE_MANUAL_TEST = "manual_test"

KNOWN_SOURCES = frozenset({SOURCE_RUNTIME, SOURCE_MANUAL_TEST})


def normalize_source(source: str | None) -> str:
    """Only an explicit, exact `manual_test` opts out of the default.
    Anything else -- None, an unrecognized string, or even a caller
    that redundantly passes "runtime" itself -- normalizes to the same
    default bucket, since nothing is gained by rejecting an unexpected
    value here versus just treating it as the common case."""
    return SOURCE_MANUAL_TEST if source == SOURCE_MANUAL_TEST else SOURCE_RUNTIME
