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

As of Developer Distribution & Sandbox v1, this no longer requires the platform Operator Key, a
repository checkout, or any admin intervention. Read `SDK_QUICKSTART.md` for the SDK call
reference, or `EXTERNAL_QUICKSTART.md` for the short, external-developer-facing version. The
complete zero-to-first-Decision path is:

1. **Get a sandbox.** `POST /v1/sandbox/organizations` with `{"email": "you@example.com"}` --
   public, no credential required (that's the point), rate-limited, capped at one per email.
   Returns a ready-to-use API key, a dashboard login, and the id of a starter Runtime Policy
   already deployed for you. See "Sandbox" below for exactly what this endpoint does and doesn't
   let you do.
2. **Install the SDK.** `pip install -e sdk-python/` from a local checkout today (see
   "Installation" below for the real, current state of public PyPI distribution).
3. **Register a test Agent.** `agent.register(name=..., principal="Sandbox Principal")` -- real,
   live, one call, using the API key step 1 returned.
4. **The starter policy already exists.** Provisioned automatically in step 1, through the real,
   unmodified create -> submit-for-review -> approve -> compile -> deploy lifecycle -- not a
   shortcut. See "Starter policy templates" below for two more you can add by hand for Human
   Review / higher-assurance scenarios.
5. **Submit one test action.** `agent.authorize(principal="Sandbox Principal",
   operation="purchase_order_create", resource=...)`.
6. **Interpret the Decision.** `ALLOW`/`DENY`/`HUMAN_REVIEW`, exactly one of the three, with real
   Evidence and an Authorization Receipt behind it -- see `SDK_QUICKSTART.md` step 3/4.

`sdk-python/examples/quickstart.py` runs steps 1, 3, 5, and 6 against a real, live backend in one
script -- no Operator Key, no repository access beyond installing the SDK itself. **Time to first
Decision is a product design target of under an hour, not a measured commercial claim** -- see
"What was and wasn't measured" below for exactly what was and wasn't verified this milestone.

### Sandbox

A sandbox Organization is a real Organization on the same, already-deployed backend, running the
exact same authority pipeline as production -- never a second, simplified engine, and never a
frontend simulation (the interactive product demo, `VITE_PUBLIC_DEMO_MODE`, is confirmed
frontend-only and is explicitly not what this is; see "What this is not" below). It's distinguished
by one field, `Organization.environment` (`"sandbox"` or `"production"`), which is never a security
boundary on its own -- tenant isolation is, and remains, `organization_id`-scoped regardless of
this label, the same guarantee every Organization already had.

**What `POST /v1/sandbox/organizations` does**, all through real, unmodified, already-tested
service functions, not new authority mechanism:
- Creates a real Organization (`environment="sandbox"`) and its Owner, via
  `organization_lifecycle_service.create_organization` -- the exact function the (still
  Operator-Key-only) admin org-creation path already used, just with one new parameter.
- Provisions one starter Runtime Policy through its real lifecycle, approved by that same new
  Owner -- the identical self-service path any Owner already has for their own organization, not a
  governance bypass.
- Mints one scoped API key via `auth_service.generate_api_key`, the same mechanism
  `POST /v1/organization/api-keys` already uses for self-service key creation.

**What it deliberately does not do**: expose or require the platform Operator Key; let a caller
choose `environment="production"`; grant access to any other organization, sandbox or production.

**Limits** (enforced only for `environment="sandbox"`, never for production):

| Resource | Limit |
|---|---|
| Sandbox organizations per email | 1 (non-archived) |
| Sandbox-creation requests | 3 per IP per hour (a dedicated, stricter limit than the general per-IP request limit) |
| Agents per sandbox | 5 |
| Runtime Policies per sandbox | 10 |
| Integration Identities per sandbox | 3 |

**Data lifecycle**: a sandbox Organization is not automatically deleted. `scripts/
cleanup_stale_sandboxes.py` (real, callable, reuses the unmodified deactivate -> archive sequence)
archives sandboxes older than a given age -- run it manually, or wire it into your own scheduler
(cron, a GitHub Actions scheduled workflow, an Azure WebJob). It is **not** wired into anything
automatically by this milestone; that remains a disclosed, explicit operational requirement.

**Dashboard**: a logged-in sandbox Owner sees a small "Sandbox" badge on Organisation Settings
(reusing the existing `StatusBadge` left-border pattern) -- no other dashboard change was made; a
sandbox organization is otherwise a completely normal organization in every other screen.

**What this is not**: not a new, simplified sandbox authority engine; not the frontend-mocked
interactive demo; not a promotion path into production (see "Sandbox-to-production boundary" below
-- none exists, deliberately).

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

`pip install -e sdk-python/` from a local checkout is still the only install path actually proven
to work end to end. As of Developer Distribution & Sandbox v1, the package itself is real-PyPI-ready
(MIT-licensed, real `LICENSE` file, correct classifiers/metadata, a clean sdist/wheel actually built
and `twine check`-passed this milestone, a `sdk-vX.Y.Z`-tagged release workflow using PyPI Trusted
Publishing) -- but **it is not yet published to PyPI**. `pip install payreality` does not work
publicly today. The remaining step, registering this repository's release workflow as a PyPI
Trusted Publisher for the "payreality" project name, requires a PyPI account with ownership of that
name, which this milestone did not have access to -- see the final report's "package publication
status" section for exactly what was and wasn't completed. No documentation or website copy claims
`pip install payreality` works publicly; none should, until that step is actually done and verified
from a genuinely fresh environment.

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

Superseded by Developer Distribution & Sandbox v1 -- see the "Sandbox" subsection under the
Quickstart above for the real, now-built mechanism (`POST /v1/sandbox/organizations`, real backend,
real authority pipeline, tenant-isolated, resource-capped). This section originally disclosed that
no sandbox existed yet; that gap is what the later milestone closed. The interactive product demo
(`VITE_PUBLIC_DEMO_MODE`) remains, separately, a **frontend-only mock** -- still true, still not
what "sandbox" refers to anywhere in this document.

## Sandbox-to-production boundary

Deliberately no promotion mechanism exists, and none was added. A sandbox Organization is a real,
fully-functional Organization -- but getting from "it worked in my sandbox" to a real production
customer relationship is, and remains, deliberate enterprise onboarding: a real Organization created
through the existing Operator-Key-gated path, its own Runtime Policies authored and approved fresh
(a sandbox's starter policy is never copied or migrated anywhere), its own Agents and Integration
Identities registered fresh, its own review of what assurance level each action actually needs. Nothing
about a sandbox's configuration, credentials, or Capability history carries over. This is treated as
a security property, not a gap to eventually close: sandbox authority must never silently become
production authority.

## Hostile security review

A deliberate pass against this milestone's own attack list, each mapped to the specific test that
exercises it -- not inferred from code presence alone:

| Attempt | Result | Proof |
|---|---|---|
| A sandbox's own credential presented against a *different* sandbox organization's data | Rejected -- the credential resolves to its own `organization_id` only, the same tenant-scoping every credential already has | `test_sandbox.py::test_sandbox_org_cannot_see_a_different_sandbox_orgs_agents` |
| A sandbox's own credential presented against a *production* organization's data | Rejected, same mechanism | `test_sandbox.py::test_sandbox_org_cannot_see_a_production_orgs_agents` |
| "Sandbox credential used against production" / "production credential used against sandbox" | Not possible by construction -- a credential's `organization_id` is fixed at creation and never chosen by the caller at request time; there is no code path where presenting a credential lets a caller name a *different* organization to act as | `test_sandbox.py::test_sandbox_api_key_resolves_only_its_own_organization` |
| Creating more Agents/Runtime Policies/Integration Identities than the sandbox cap | Rejected (`SandboxLimitExceededError`, HTTP 403), production organizations unaffected | `test_sandbox.py::test_sandbox_agent_cap_is_enforced`, `test_sandbox_integration_identity_cap_is_enforced`, `test_production_organization_is_never_capped` |
| Requesting a second sandbox for an email that already has one | Rejected (409) | `test_sandbox.py::test_second_sandbox_for_the_same_email_is_refused` |
| Bursting `POST /v1/sandbox/organizations` past the per-IP rate limit | Rejected (429); a different IP's own budget is untouched | `test_sandbox.py::test_sandbox_creation_rate_limit_is_enforced`, `test_rate_limit_is_scoped_per_ip_not_global` |
| Creating a privileged IntegrationIdentity or an unrestricted Runtime Connection from a sandbox | Not a distinct privilege to escalate to -- IntegrationIdentity/Runtime Connection creation is the same self-service, `require_permission`-gated, org-scoped path every organization (sandbox or production) already has; a sandbox's own Owner can only ever act within its own organization, capped by the same limits above | Code inspection: `routers/integration_identities.py`, `routers/enforcement_bindings.py`, both `require_permission`-gated, never Operator-Key-exclusive |
| Sandbox configuration silently reaching production | Not possible -- no promotion mechanism exists at all (see "Sandbox-to-production boundary" above); a negative-space check, not a test of removed functionality | Code inspection: no code path anywhere copies a sandbox Organization's rows into a different Organization |
| Stale-sandbox cleanup touching a production organization, or a non-stale sandbox | Rejected -- `environment == "sandbox"` and `created_at` age are both required | `test_sandbox.py::test_stale_sandbox_cleanup_only_touches_old_sandbox_orgs` |
| The sandbox-creation endpoint itself being unintentionally left ungated | Caught by this repo's own pre-existing route-permission-gate guard test, which flags any `/v1/*` route with no `require_permission`/`verify_operator_key` dependency and no reviewed, justified exemption -- the sandbox route's public-by-design status is now a recorded, reviewed exemption, not an oversight | `test_route_permission_gates.py::test_every_v1_route_is_permission_gated_or_explicitly_justified` |

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

## What was and wasn't measured, across both milestones

- **Code inspection**: every claim in this document about what the platform does today was
  verified by reading the actual source, not inferred or assumed -- including, this milestone,
  Organization/RBAC/tenant-isolation code read before choosing the sandbox mechanism, per Developer
  Distribution & Sandbox v1's own explicit instruction not to guess.
- **Unit/integration test proof**: `HttpApiAdapterTemplate`/`CapabilityEnforcer`/typed Capability
  exceptions (Integration Kit v1), and the sandbox creation/isolation/caps/rate-limit/cleanup tests
  (Developer Distribution & Sandbox v1, real SQLite + real ephemeral OPA) all pass. See the latest
  final report for exact counts.
- **Package build proof**: `python -m build` + `twine check` were actually run this milestone
  against the real package; both passed.
- **Clean-environment install proof**: the built wheel (not editable) was actually installed into a
  fresh, empty virtualenv and every public module imported and smoke-tested successfully.
- **Package publication proof**: unavailable -- no PyPI account/credentials exist in this
  environment. The release workflow was written and is ready; the one-time Trusted Publisher
  registration on pypi.org was not, and could not be, completed here.
- **Hosted sandbox proof**: see the final report's own "sandbox deployment status" and "clean
  developer acceptance test" sections for exactly what was verified against the real, live,
  deployed backend versus only locally.
- **Not measured, disclosed plainly**: a full, real "time to first Decision" timing run performed
  by an actual unfamiliar developer. What this milestone did measure is disclosed precisely,
  separated from provisioning/deploy wait time, in the final report -- "under an hour" remains a
  stated product design target, never asserted as a proven, general result.
