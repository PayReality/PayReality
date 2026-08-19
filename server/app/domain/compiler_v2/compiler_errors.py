"""Structured compiler diagnostics.

Same discipline as runtime_policy/validators.py: compile_bundle() and
every stage inside it always returns a CompilerDiagnostics, never raises,
for any RuntimePolicy input no matter how invalid or how many conditions
it has that would once have silently become inert metadata. A raised
exception out of this package means a genuine programming error (e.g. a
caller passing something that isn't a RuntimePolicy at all), never "the
policy has a mistake in it."
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompilerError:
    code: str
    message: str
    policy_id: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class CompilerDiagnostics:
    errors: tuple[CompilerError, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def merged_with(self, other: "CompilerDiagnostics") -> "CompilerDiagnostics":
        return CompilerDiagnostics(errors=self.errors + other.errors)


# Stable error codes, referenced directly by tests and (eventually) by
# whatever UI surfaces these, so they must not be restated ad hoc as raw
# strings scattered across the compiler's modules.
UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"
MALFORMED_CONDITION = "MALFORMED_CONDITION"
INVALID_RESOURCE = "INVALID_RESOURCE"
INVALID_ACTION = "INVALID_ACTION"
INVALID_FIELD = "INVALID_FIELD"
CONFLICTING_POLICY_STRUCTURE = "CONFLICTING_POLICY_STRUCTURE"
INVALID_RUNTIME_POLICY = "INVALID_RUNTIME_POLICY"
REGO_GENERATION_FAILED = "REGO_GENERATION_FAILED"
