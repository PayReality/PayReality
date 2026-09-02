# PayReality Integration Kit v1

Turns the real, already-correct integration primitives (Phases 5.1/6/6.1) into repeatable,
documented, tested patterns. This is productization, not new architecture: no trust model changed,
no new backend service was introduced for the Adapter template or the enforcement middleware, and
the PDP/PEP boundary is exactly what it was before this kit -- PayReality decides and authorizes;
a customer-operated enforcement point acts on that authorization.

## Progressive assurance

Adopt in stages. Nothing below requires the stage after it.

**Stage 1 -- Agent SDK / Runtime API -> a real Decision.** The lowest-friction path: an Agent
submits its own signed request, Runtime Authority evaluates it, you get back Allow, Deny, or Human
Review. Suitable for lower-assurance or advisory use cases where you control the Agent and accept
its own submitted context. See the Quickstart below.

**Stage 2 -- Trusted Adapter -> trusted observation.** For a real attempted enterprise operation
that needs independent corroboration (the Agent's own description isn't sufficient proof of what
your enterprise system is actually being asked to do), a customer-controlled Trusted Adapter
reports it through an approved Action Mapping. See "Adapter Template" below.

**Stage 3 -- Capability Authorization -> controlled execution.** For actions that need stronger
execution control, Runtime Authority (directly, or after Human Review approval) can issue a
short-lived, single-use Capability Authorization. Your own enforcement boundary verifies and
consumes it before letting the downstream operation proceed. See "Enforcement Middleware" below.

Start with Stage 1. Add Stage 2 where the real attempted operation needs independent observation.
Add Stage 3 where an action needs stronger execution control. None of this weakens what a higher
stage already guarantees -- Stage 3's Capability verification carries every invariant listed under
"Security invariants" below regardless of which stage issued the underlying Decision.

## Quickstart: zero to first Decision

Read `SDK_QUICKSTART.md` for the SDK call reference. The complete zero-to-first-Decision path,
including the parts `SDK_QUICKSTART.md` assumes already exist, is:

1. **Organization.** Not self-serve today: creating a new organization requires the platform
   Operator Key (`POST /v1/organizations`, an administrative action -- see
   `routers/organization_lifecycle.py`). A new developer today gets an organization from the
   PayReality team, or holds the Operator Key themselves in a self-hosted/eval context. This
   milestone does not add self-serve signup, and does not pretend it exists.
2. **Register the Agent.** `agent.register(name=..., principal=...)` -- real, live, one call.
3. **Install the SDK.** `pip install -e sdk-python/` from a local checkout -- see "Installation" below for why this, and only this, is the real supported path today.
4. **Create one starter policy**, through the real, unmodified lifecycle (create -> submit-for-review -> approve -> compile -> deploy). See "Starter policy templates" below for three ready-to-adapt examples. Applying a template never skips review or approval -- it's a starting point for an authored, approved policy, not a bypass.
5. **Submit one test action.** `agent.authorize(principal=..., operation=..., resource=...)`.
6. **Interpret the Decision.** `ALLOW`/`DENY`/`HUMAN_REVIEW`, exactly one of the three, with real Evidence and an Authorization Receipt behind it -- see `SDK_QUICKSTART.md` step 3/4.

`sdk-python/examples/quickstart.py` runs all six steps in one script. **Time to first Decision is a
product design target of under an hour, not a measured commercial claim** -- see "What was and
wasn't measured" below for exactly what was and wasn't verified this milestone.

### Starter policy templates

Not a policy marketplace, not a one-click "apply template" API (no such endpoint exists, and this
milestone doesn't add one) -- three reference `RuntimePolicy` request bodies to copy, adapt, and
push through the real `POST /v1/runtime-policies` -> `submit-for-review` -> `approve` -> `compile`
-> `deploy` lifecycle exactly like any other policy:

**Sensitive account change requires Human Review:**
```json
{
  "name": "Disable user requires review",
  "scope": { "principal": "<your principal>", "action": "disable_user" },
  "conditions": [],
  "effect": "require_human_review"
}
```

**High-value financial action requires Human Review:**
```json
{
  "name": "Wire transfer over 10000 requires review",
  "scope": { "principal": "<your principal>", "action": "wire_transfer" },
  "conditions": [{ "field": "amount", "operator": "gt", "value": 10000 }],
  "effect": "require_human_review"
}
```

**Low-risk reference action allowed:**
```json
{
  "name": "Purchase order creation allowed",
  "scope": { "principal": "<your principal>", "action": "purchase_order_create" },
  "conditions": [],
  "effect": "allow"
}
```

A fourth case the brief for this milestone names -- "unauthorized Agent denied" -- isn't a policy
at all: it's the platform's existing default fail-closed behavior. An action with no matching
policy, or an Agent outside the delegated authority a policy does cover, already resolves to
`DENY` or `HUMAN_REVIEW` (never a silent `ALLOW`) with zero configuration. Documented here as
existing behavior, not fabricated as a fourth template.

## Adapter Template (Stage 2)

`payreality.adapter_templates.HttpApiAdapterTemplate` is the one generic Trusted Adapter template
this milestone ships, built entirely on top of the already-real, already-tested
`payreality.integration.Adapter.attest()` -- it adds configuration-driven field extraction in
front of that call, nothing else. **Only one template ships.** A webhook receiver, a message-queue
consumer, and a reverse-proxy/gateway plugin all reduce to the identical shape ("some trigger hands
you a payload dict, extract fields per configuration, call `attest()`") -- they are the same
pattern with a different trigger, not implemented or tested separately in v1.

```python
from payreality.adapter_templates import AdapterFieldRules, HttpApiAdapterTemplate

fields = AdapterFieldRules(
    source_operation="ChangeSupplierBankDetails",   # fixed -- never read from the payload
    action="supplier_bank_details_change",          # fixed -- never read from the payload
    origin_agent_id_source="agent.id",              # dotted path into the incoming payload
    external_operation_id_source="operation.id",    # required -- this template never invents one
    resource_source="supplier.reference",
)

template = HttpApiAdapterTemplate(
    integration_identity_id="<registered IntegrationIdentity id>",
    certificate_id="<its active certificate id>",
    private_key="<its private key, never leaves your process>",
    enforcement_binding_id="<the approved Runtime Connection id>",
    fields=fields,
)

decision = template.handle(raw_payload)  # raw_payload: whatever your own receiver already parsed
```

**What this does:** receives the payload your own code already observed, extracts each configured
field (a dotted path or a callable), fails closed (`ConfigurationError`, before any network call)
if a required field is missing, and submits the real attested Intent -- preserving
`external_operation_id`, authenticating as the IntegrationIdentity (never as the Agent), and never
letting the payload choose the canonical action or source operation.

**What this does not do:** it does not register the IntegrationIdentity, author or approve the
Integration Contract (Action Mapping), or create the Runtime Connection (Enforcement Binding) --
those are administrative setup, performed via the existing `integration_identity_service`,
`integration_contract_service`, and `enforcement_binding_service` functions (or their routers)
before this class is ever constructed, exactly the same division of responsibility
`payreality.integration.Adapter` itself already documents. It does not draft an Action Mapping
with AI assistance -- no such mechanism exists in this repository today (unlike RuntimePolicy,
which does have AI-assisted drafting with human promotion); Action Mapping configuration stays
fully human-authored and human-approved.

## Enforcement Middleware (Stage 3)

`payreality.enforcement.CapabilityEnforcer` is a plain, framework-agnostic Python callable/decorator
-- not a new ASGI/FastAPI-specific dependency, not a new ecosystem -- built entirely on top of the
already-tenant-scoped, already-freshness-checked `Agent.verify_capability()`. It replaces
hand-writing the verify-and-consume lifecycle the way `scripts/reference_enforcement_adapter.py`
(still real, still valid, kept unchanged) does today with its own hand-rolled HTTP calls.

```python
from payreality import Agent
from payreality.enforcement import CapabilityEnforcer

agent = Agent(bearer_token="<a tenant-bound API key with Permission.CAPABILITY_VERIFY>")
enforcer = CapabilityEnforcer(agent=agent, audience="my-service", environment="production")

def execute_downstream(consumed_capability):
    # Your own business system call. `consumed_capability` proves the
    # Capability was verified and consumed exactly once; it does not
    # prove whatever this function does next actually succeeds -- that
    # remains a separate fact, exactly as scripts/reference_enforcement_
    # adapter.py's own two-line output already keeps them.
    return call_my_erp(...)

result = enforcer.enforce(
    token, action="supplier_bank_details_change", resource="supplier:SUPPLIER_482",
    constraints={}, downstream=execute_downstream,
)
```

`downstream` is called only after a successful verify-and-consume, receives the `ConsumedCapability`
(never conflated with its own return value), and is never called at all if verification fails for
any reason -- see "Security invariants" below for the exhaustive list of what still causes a
rejection.

### Middleware configuration

Configured once per enforcement checkpoint: `agent` (the verifier's own credentials -- tenant
scoping comes from which organisation this credential resolves to, never a separate parameter),
`audience`, and optionally `environment`/`enforcement_binding_id` (Runtime Connection). Called once
per proposed downstream operation: `token`, `action`, `resource`, `constraints`, optionally
`principal`. This keeps action/resource as call-site arguments (the caller's own downstream-request
handler already knows what operation it's about to perform) rather than a second, configuration-time
resolver abstraction -- the narrower of the two shapes the original design considered, chosen to
avoid inventing indirection this milestone doesn't need.

### Security invariants preserved (Phases 5.1, 6, 6.1)

`CapabilityEnforcer` adds zero new verification logic -- it calls `Agent.verify_capability()`
unchanged, so every one of these is inherited, not reimplemented: one Decision produces at most one
Capability, ever; single-use (a second presentation of a consumed token is rejected); no automatic
renewal; tenant-scoped verification (a verifier for one organization cannot consume another
organization's Capability); relevant live state (Agent, Organization, IntegrationIdentity,
Enforcement Binding) rechecked immediately before consumption, failing closed if any is no longer
active; wrong action, resource, environment, binding, or audience each independently rejected; an
already-consumed or expired Capability rejected. `downstream` is never called on any of these.

## Integration recipe: Supplier bank details change

The one fully worked recipe this milestone ships (a second, "high-value refund," was scoped as a
candidate, not required, and is not built):

1. Register an Agent (`AP-Invoice-Agent`).
2. Configure an Integration Contract mapping `ChangeSupplierBankDetails` -> `supplier_bank_details_change` (`integration_contract_service.create_contract_version` / `validate_contract_version` / `approve_contract_version`).
3. Configure a Human Review policy for that action (the starter template above).
4. Submit through `HttpApiAdapterTemplate.handle(...)`.
5. A reviewer approves the resulting `HUMAN_REVIEW` decision.
6. Issue a Capability from that approval (`agent.request_capability_from_review(...)`).
7. Enforce it through `CapabilityEnforcer.enforce(...)`.
8. Present the same token again -- rejected (`CapabilityAlreadyConsumedError`), proving replay rejection.
9. Inspect Evidence and the Authorization Receipt for the full, unrewritten history: the original decision still reads `HUMAN_REVIEW`, the resolution and Capability state are separate, linked records.

This composes the new Adapter template and enforcement middleware together end to end; the
underlying Trusted-Adapter and Capability mechanics were already exhaustively proven server-side by
`test_reference_enforcement_demonstration.py` and `test_integration_runtime_path.py` and are not
re-proven here -- see `sdk-python/tests/test_supplier_bank_details_recipe.py` (new) for the
composition-specific proof: the Adapter template's own output feeds a real capability-issuance
call, and the resulting token feeds the middleware, including the required replay-rejection step.

## Installation

The only real, supported install path today is a local editable install from a checkout of this
repository: `pip install -e sdk-python/`. There is no PyPI package, no private package registry,
and no CI job that publishes one -- confirmed by inspection of `sdk-python/pyproject.toml` and
`.github/workflows/ci.yml` (which this milestone extends with a test job, not a publish job). Any
documentation or website copy describing a different install method would be inaccurate; none was
found this milestone, and none was introduced.

## Trusted Enterprise Facts (documented direction, not built in v1)

Today: one generic, signed-attestation ingestion path (`fact_service.ingest_fact`) -- a
`FactSource` registers a public key, and every fact must arrive as an ED25519-signed attestation
verified against it. There is no pluggable "source adapter" concept yet; every source looks the
same to the platform regardless of where the fact actually originates.

**Recommended future direction, not implemented this milestone:** pluggable source adapters --
API-sourced facts (polling or webhook-pushed from an enterprise system), identity-sourced facts
(from an IdP/HR system), database-sourced facts (a direct, read-only connection to a system of
record), managed static facts (an admin-entered value with its own expiry), and other approved
source types, each producing the same signed `EnterpriseFact` shape underneath. Building this is
explicitly out of scope for Integration Kit v1 (a "full Fact Provider framework" is an explicit
exclusion) -- named here so the next milestone that picks it up has a concrete starting point.

The truth model does not change: PayReality authenticates the source, provenance, and validity
window of an enterprise assertion. It does not, and will not, claim to independently verify the
underlying business fact -- the source system remains responsible for that.

## Sandbox

No new sandbox system was built, and none should be inferred from this document. Today's real
options are: (a) run the actual backend locally against a real Postgres + OPA (see
`DEPLOYMENT.md`'s local-run instructions and `docker-compose.yml`) -- this is genuinely the same
code path production uses, just running on your machine; or (b) the interactive product demo
(`VITE_PUBLIC_DEMO_MODE`), which is a **frontend-only mock** (`src/app/demo/mockRouter.ts`) that
narrates the Agent/policy/Human-Review/Capability story for illustration but never calls a real
backend, real OPA, or real Capability service -- confirmed by inspection this milestone, and
disclosed here explicitly rather than left to imply otherwise. A real, dedicated hosted sandbox
organization (test Agent, test policy, a sample mapping, a simulated downstream action, a full
Capability round trip, all pre-wired and safe to break) is a reasonable future direction; it is not
built, and is not claimed as built, in v1.

## Integration health (recommended future enhancement, not built in v1)

`assurance_service.get_summary` (`GET /v1/assurance/summary`) already reports real Agent, policy,
decision, review, and evidence counts today. What it does not yet report, and what a future
milestone should add as a small, additive extension to that same function (no new model, no new
endpoint): active/total IntegrationIdentity counts, active/total Enforcement Binding ("Runtime
Connection") counts, an approved-Action-Mapping count, a `last_decision_at` timestamp, and
Capability issued/consumed/consumption-failed counts. Deliberately not built this milestone --
Integration Kit v1 is scoped to productizing existing integration primitives, not extending the
assurance surface; this section exists so the exact extension point is documented for whoever picks
it up next.

## What was and wasn't measured this milestone

- **Code inspection**: every claim in this document about what the platform does today (the
  install path, the Adapter/Capability service functions, the vocabulary, the assurance summary's
  current fields, the Trusted Enterprise Facts model) was verified by reading the actual source,
  not inferred or assumed.
- **Unit/integration test proof**: the new `HttpApiAdapterTemplate` and `CapabilityEnforcer`
  classes, and the new typed Capability exceptions, are covered by real, passing tests (SDK-level,
  mocked HTTP layer, and one new real-SQLite-plus-OPA server-side test for a previously-untested
  gap -- a revoked IntegrationIdentity cannot submit a new attested intent). See the milestone's
  final report for exact counts.
- **Package installation proof**: `pip install -e sdk-python/` was actually run in this
  environment against the updated package; see the final report for the result.
- **Not measured, disclosed plainly**: a full, live, network-round-trip "time to first Decision"
  timing run. This environment's Docker daemon is not reachable (the same, already-established
  limitation this repository's own Postgres-gated tests disclose), so a real Postgres + OPA + a
  running server were not available to boot `examples/quickstart.py` against over HTTP. "Under an
  hour" remains a stated product design target, not a number this milestone proved.
