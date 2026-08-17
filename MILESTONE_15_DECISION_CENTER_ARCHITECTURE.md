# Milestone 15: Decision Center Device-Bound-Key Architecture

## What was actually investigated

There are two distinct signing paths in this codebase, and Milestone 14's finding conflated them.
Separating them is the precondition for a correct decision.

**Path 1 -- real agent-to-PayReality authorization (`POST /v1/intents`, `verify_agent_signature` in
`server/app/dependencies.py`).** An agent (a real, running piece of software, integrated via the Python
SDK) generates and holds its own Ed25519 key pair in its own runtime. PayReality only ever receives the
public key (at registration) and a per-request signature (`X-PayReality-Signature`) over the raw
request body. The private key never leaves the agent's own process. This is a standard machine-identity
/ non-repudiation pattern (the same shape as mTLS client certificates or a SPIFFE/SPIRE workload
identity), and it is **already correctly separate from human identity**: an agent's certificate has no
relationship to any `User` row, `Role`, or session token anywhere in the schema (`server/app/db/models.py`
confirmed -- `Agent`/`Certificate` and `User`/`UserSession` share no foreign key). A human's role change
has **zero effect** on any agent's signing capability, and vice versa. This is correct separation of
concerns, not a gap.

**Path 2 -- the Decision Center's browser-based test tool (`src/app/live/pages/LiveTestIntent.tsx`,
`src/app/live/agentKeyStore.ts`).** For a human exploring or testing the platform without running real
agent code, this page generates a throwaway key pair **in the browser's own `localStorage`** and lets
that browser sign a test intent as if it were an agent. `agentKeyStore.ts`'s own header comment states
this plainly: "this UI plays the role of 'the agent' for demo purposes... a real Agent integration
generates and holds its own key pair in its own runtime and never hands the private key to a browser."
This was always a labeled simplification, not a claimed production integration path.

**Milestone 14's finding, restated precisely**: the Decision Center's "submit a signed test intent"
dropdown only lists agents whose private key happens to exist in *this specific browser's*
`localStorage` -- which permanently excludes any agent registered via the real SDK path, or registered
from a different browser/device. This is real and worth a decision, but it is **not** a defect in the
real authorization path (Path 1 already works correctly and independently of this UI), and it does
**not** affect observability: `LiveEvidence.tsx`, the Agent Directory, and Decisions/Evidence list
endpoints already show every agent's real activity regardless of which device holds its key, because
those are plain organization-scoped reads, not signature operations.

## Answering the investigation's specific questions

- **Why the architecture exists**: asymmetric-key signing is the correct way to let PayReality verify
  "this specific agent authorized this specific request" without PayReality ever needing custody of the
  agent's private key -- the same reason TLS client certs and SPIFFE SVIDs work this way.
- **What security property it provides**: non-repudiation and impersonation-resistance. No party other
  than the agent's own runtime can produce a valid signature, including PayReality's own servers.
- **What operational limitations it creates**: exactly one, and it is confined to the browser test tool
  described above -- a human cannot submit a *test* intent "as" an agent whose key they don't hold. This
  is not a limitation on the agent itself; it is definitionally what a private key is for.
- **How enterprise deployments would provision devices**: already solved for the real path -- an agent
  is provisioned by generating its key pair in its own runtime and calling `POST /v1/agents` to register
  the public key (`AGENT_REGISTER` permission), exactly matching the SDK's documented flow.
- **What happens when a device is replaced**: already solved -- `POST /v1/agents/{id}/rotate`
  (`AGENT_ROTATE` permission, wired to `AgentDetailPage.tsx`'s "Rotate certificate" action) issues a new
  certificate for a freshly generated public key without re-registering the agent's identity. This is
  the existing answer to "the agent's runtime moved to new infrastructure."
- **What happens when an employee changes role**: nothing, and that is correct -- confirmed above, an
  agent's certificate has no relationship to any human's `Role`. A role change is a `PATCH
  /v1/users/{id}/role` operation (`USERS_MANAGE`), entirely orthogonal to agent certificates.
- **What happens when an agent moves between environments**: not automatically carried over today (a
  certificate is registered per-agent per-organization), which is arguably the *correct* default for a
  zero-trust posture -- an agent acting in a materially different environment (e.g., staging vs.
  production) having a distinguishable identity is a feature, not a missing capability. **RECOMMENDED,
  not built**: if a customer wants an explicit "promote this agent's identity from staging to
  production" flow, that would be new, deliberate scope, not a fix to existing behavior.
- **Whether the model works with enterprise identity providers**: this question conflates two different
  identity domains. Agent-to-PayReality signing (machine identity) does not need to, and should not,
  route through a human-facing IdP (SSO/OIDC/SAML) -- forcing that would be a category error, the same
  way a TLS client cert doesn't authenticate via a company's SSO portal. Human identity (the `/v1/auth`
  session model) is the correct, already-separate place for a future SSO integration, and is unaffected
  by anything discussed in this section.
- **Whether the design creates unnecessary operational friction**: only in the one already-identified
  place -- the browser test tool's dropdown -- and the friction is inherent to what a private key is,
  not an accidental design flaw.
- **Whether keys are truly bound to the appropriate authority**: yes, confirmed -- a certificate is
  bound to exactly one `Agent`, which is bound to exactly one `Principal` (`acting_for_principal_id`),
  which is bound to exactly one `Organization`. No cross-binding path exists.
- **Whether the architecture is compatible with future Runtime Authority deployment models**: yes --
  this is precisely the model most workload-identity-based enterprise deployments already expect
  (a service authenticates itself, not a human on its behalf), and needs no change to accommodate
  Enterprise Knowledge, which is a retrieval/grounding concern with no relationship to how an agent
  proves its own identity.

## Decision

**Option A -- Keep**, with one small, low-risk clarification (not an architecture change):

The signing architecture itself (Path 1) is sound and should not change. The browser test tool (Path 2)
should also be kept -- it is a legitimate, working convenience for exploring the platform -- but its own
UI copy should make the distinction in this document explicit, since Milestone 14 itself was misled by
the current framing: the dropdown should read as "agents you can submit a *test* signed intent as in
this browser" rather than implying it is the complete list of the organization's agents (which is
already correctly and separately visible via the Agent Directory and Decisions/Evidence, unaffected by
this limitation). **RECOMMENDED, not implemented this milestone**: a one-line copy change plus a link
to the existing Policy Simulation / dry-run feature (`POST /v1/runtime-policies/{policy_key}/dry-run`,
already gated correctly by `RUNTIME_POLICY_VIEW` as of this milestone's own fix) as the right tool for
"what would happen if agent X submitted this," which needs no signature and already works for any
agent regardless of key custody.

**Why not Option B (modify)**: the only concrete "modification" available -- letting a human submit a
signed test intent on behalf of an agent whose key they don't hold -- would require either a
server-side signing capability (defeats the entire non-repudiation purpose of the signing model, a real
security regression) or provisioning a new key pair for a new test identity (which already works today
via ordinary agent registration). There is no safe, real modification to make here.

**Why not Option C (replace)**: replacing Ed25519 agent-held keys with a centrally issued/managed model
(HSM-backed PKI, SPIFFE/SPIRE) is a legitimate *future* evolution for organizations at a scale where key
lifecycle management (bulk rotation, revocation lists, hardware attestation) becomes operationally
significant, but nothing in this codebase's current scale or Enterprise Knowledge's own requirements
calls for it now. Recommended as a noted future option, not a current blocker.

## Relevance to Enterprise Knowledge readiness

None. Enterprise Knowledge is a retrieval/grounding concern; nothing about how an agent proves its own
identity changes based on whether Enterprise Knowledge exists. This workstream's own finding is:
**not a blocker**, closed with an explicit decision (Option A) rather than left open.
