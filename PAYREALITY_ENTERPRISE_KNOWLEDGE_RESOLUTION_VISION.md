# Enterprise Knowledge Resolution — An Architecture Vision for PayReality's Next Foundational Layer

**Status:** Living document. Version 0.1.
**Audience:** Senior engineers, enterprise architects, and future team members.
**Nature of this document:** Exploratory. This is not a design specification, not an implementation plan, and not a decision record. It exists to define the architectural space PayReality must eventually explore, to name the assumptions embedded in the platform as it exists today, and to record open questions faithfully rather than resolve them prematurely. Wherever multiple approaches are possible, they are documented side by side. Nothing in this document should be read as a commitment.

**How this document should evolve:** Sections should be amended in place as understanding sharpens, with old reasoning struck through or annotated rather than deleted, so the document preserves its own history of thought. A section moving from "open question" to "resolved" should be an explicit, visible event — accompanied by the reasoning that resolved it — not a silent edit. See the changelog convention at the end.

---

## 1. The Architectural Problem

Runtime Authority, as it exists today, answers one question with total rigor: **given a set of facts, does policy permit this action?** It does this deterministically, auditably, and fast — an OPA evaluation against a compiled policy bundle, with every decision cryptographically recorded as Evidence. This is a genuine, hard-won capability, and nothing in this document questions its correctness for the question it actually answers.

But that question — "does policy permit this action, *given these facts*" — silently presupposes that the facts handed to it are true. Runtime Authority has no mechanism, and no architectural role, for asking whether they actually are. It is, by design, a perfect reasoner over an assumed world, not an investigator of the real one.

This is easy to miss because many of the facts a policy references today are cheap, self-evident, or already present in the shape of the request itself: an amount, a currency, a principal's declared role. These are facts Runtime Authority can treat as given because they arrive as part of the very intent being evaluated — there is no meaningful gap between "what must be true" and "is it true," because the request *is* the assertion of truth (an agent submitting an intent to pay $40,000 is, among other things, asserting that the amount is $40,000).

The gap opens the moment a policy needs to reference a fact that lives **outside** the request — a fact about the state of the enterprise itself, not about the shape of this particular action. Consider:

- `VendorApproved`
- `AMLPassed`
- `BudgetAvailable`
- `FraudCleared`
- `ClaimEligible`
- `BankVerified`

None of these are facts an AI agent can simply assert as part of its own request in a way Runtime Authority could trust unverified — an agent claiming "the vendor is approved" is not evidence that the vendor is approved. Somewhere, something has to have actually gone and checked. Today, that "somewhere" is invisible to the platform. Either the calling application has already resolved these facts and quietly folded them into the Intent's context before submission — in which case Runtime Authority is trusting an assertion it never independently verified and has no record of having verified — or the policy simply doesn't reference such facts at all, and enforcement of those business truths happens (or doesn't happen) entirely outside the system whose entire purpose is to govern AI actions.

**The core distinction this document is built around:**

> **"What must be true?"** is a policy question — static, declarative, expressible in advance, and exactly what Runtime Policy already does well.
>
> **"Is it actually true right now?"** is a resolution question — dynamic, time-bound, dependent on the state of specific enterprise systems, and something no layer of the current architecture owns.

Collapsing these two questions into one — letting policy compilation, or policy evaluation, or the calling application, silently also be responsible for establishing whether a referenced fact is currently true — is architecturally unsound for reasons that go beyond tidiness:

- It breaks **portability**. A policy that says "budget must be available" is a business rule any enterprise could adopt. A policy that says "call this SAP endpoint and check field X" is not a policy at all — it's an integration, wearing policy's clothing, and it stops being reusable, testable, or reviewable as policy the moment it needs to know where a fact lives.
- It breaks **determinism** in exactly the place Runtime Authority has invested heavily in defending it. OPA's evaluation model is a pure function of a static input document — that's *why* Compiler V2 can guarantee the same active policy set always compiles to the same bundle hash, and why a decision can be replayed and produced identically from Evidence. The instant policy evaluation itself needs to reach out and ask a live enterprise system something, that guarantee is gone, replaced by whatever that system happened to say at whatever moment the call landed.
- It breaks **auditability of the right thing**. Evidence today proves *a decision was made and what it was*. It does not, and structurally cannot, prove that the facts feeding that decision were themselves real — because nothing in the architecture currently treats "was this fact real" as a question with its own answer, its own provenance, and its own record.

Runtime Authority alone is therefore insufficient not because it is poorly built, but because it was built to answer a narrower question than the one enterprises actually need answered. **"Is this action authorized" is not the same claim as "is this action authorized, and were the business truths it depended on actually verified."** PayReality has, so far, built the first claim extremely well. This document is about the second.

---

## 2. Current Architecture

Today's pipeline, as it exists in the platform:

```
Enterprise Documents
      ↓
Authority Intelligence
      ↓
Runtime Policies
      ↓
Runtime Authority
      ↓
Evidence
```

**Authority Intelligence** takes enterprise governance documents (delegation-of-authority memos, approval matrices, policy manuals) and, with AI assistance under human review, extracts a structured Authority Graph — principals, resources, operations, relationships, conflicts, and candidate policies — which humans review, correct, and approve. Its output is not "a policy" in the enforcement sense; it is a reviewed, explainable *candidate* for one.

**Runtime Policies** are the canonical, versioned, lifecycle-governed representation of an approved rule: a scope (who, acting on what), a set of conditions (field/operator/value comparisons), an effect (allow/deny/require-human-review), and constraints. A policy's conditions are evaluated against whatever is present in the *decision context* at evaluation time — a plain, flat set of values assembled by whoever is submitting the action for evaluation.

**Runtime Authority** compiles the current set of active Runtime Policies into a single Rego bundle and evaluates each submitted Intent against it via OPA, producing Allow, Deny, or Human-Review, deterministically and quickly.

**Evidence** cryptographically signs and records each decision — what was decided, and (implicitly) what policy version and bundle hash produced it.

**Where the architectural gap begins:** at the boundary between "Runtime Policy's condition" and "the decision context's value." A condition like `amount <= 50000` is safe today because `amount` is a property of the request itself — there is nothing to resolve; the value simply *is*. A condition that instead needed to express `VendorApproved == true` would, today, depend entirely on whoever assembled the decision context having already, somehow, correctly and currently determined that the vendor is approved — and having put that determination into the context correctly. **Nothing in the architecture today validates that this happened, records how it happened, or even requires that it happened before a decision is made.** The gap is not a missing feature inside Runtime Authority; it is a missing *layer*, sitting logically upstream of Runtime Authority and downstream of Runtime Policy, that the pipeline currently has no name for and no owner of.

---

## 3. Future Architecture

A candidate shape, explored here without being adopted:

```
Enterprise Documents
      ↓
Authority Intelligence
      ↓
Runtime Policies
      ↓
Enterprise Knowledge Resolution
      ↓
Runtime Authority
      ↓
Evidence
```

**Authority Intelligence** — likely largely unchanged in mechanism, but its scope of extraction may need to widen: today it extracts *who may do what, and under what conditions*. It may also need to extract, as a distinct artifact, *which business assertions a given governance document actually assumes* — i.e., recognizing that "invoices over $10,000 require vendor approval" is really asserting a dependency on a `VendorApproved` fact, and that this dependency is itself something worth surfacing to a human reviewer, separately from the numeric threshold. Whether this becomes a new extraction category or remains implicit inside policy conditions is an open question (see Section 13).

**Runtime Policies** — conditions would reference named business assertions directly ("VendorApproved must be true") rather than expecting a pre-resolved boolean to simply appear in context from an unspecified source. The policy author's job stays exactly what it is today: expressing what must be true. What changes is that "VendorApproved" becomes a first-class, named thing the policy points at, rather than an implicit assumption about what the caller will have already put in the context.

**Enterprise Knowledge Resolution (new)** — given the set of business assertions a candidate decision's policies actually reference, this layer is responsible for determining, for each one, whether it is currently satisfied — and, critically, for producing a state that is *not* forced into a premature true/false when the honest answer is "unknown," "expired," or "the system that would tell us is unreachable" (see Section 11). Its output is a resolved knowledge context that Runtime Authority can evaluate against exactly as it evaluates any other input today.

**Runtime Authority** — its own responsibility does not change. It remains a pure evaluator. What changes is only where its input document's values come from: previously assembled ad hoc by an untracked upstream process, now assembled by a layer whose entire purpose is producing them faithfully and recording how.

**Evidence** — must extend to capture not only what was decided, but what knowledge the decision relied on and how that knowledge was established (resolver identity, resolution method, timestamp, validity window) — without necessarily capturing the raw underlying enterprise data itself (see Section 9's data-minimization discussion). Exactly what shape this takes is open.

This is one candidate shape. An equally defensible alternative view holds that Enterprise Knowledge Resolution is not a *pipeline stage* at all but a *service Runtime Policy and Runtime Authority both consult*, more like a directory than a conveyor belt — this distinction (linear stage vs. consulted service) recurs as an open question in Section 13 and should not be considered settled by the diagram above, which is offered only as the most direct visual extension of the existing pipeline metaphor.

---

## 4. Core Architectural Principles

The following principles are offered as a starting set, each expanded, none yet battle-tested against a real implementation.

**Policies should never reference enterprise systems.** A policy that names SAP, Oracle, or a specific API is not a policy — it is an integration wearing policy's language. The moment a policy encodes *where* a fact comes from, it stops being portable across environments, stops being reviewable by someone who understands the business rule but not the IT landscape, and stops being something Authority Intelligence's explainability model can cleanly cite back to a governance document (a compliance officer can verify "budget must be available" against a finance policy; they cannot verify a REST endpoint against one).

**Policies should express business truths, not retrieval instructions.** This is the positive form of the same principle: a policy's vocabulary should be the vocabulary of the business (`BudgetAvailable`), never the vocabulary of integration (`GET /budgets/{id}/status`). This mirrors a discipline the platform already holds elsewhere — Runtime Authority's own domain model is explicitly kept ignorant of any specific business domain's vocabulary (a "financial vocabulary" adapter sits above the generic compiler, not inside it) — the same separation needs to exist one layer further out, between *what a truth is called* and *how a truth is established*.

**Enterprise Knowledge should determine how those truths are proven.** The mapping from a named assertion to an actual resolution mechanism — which system, which method, which credential, which cache policy — is configuration and capability that belongs entirely inside Enterprise Knowledge Resolution, invisible to both the policy author and to Runtime Authority. This is the principle that actually creates the portability the first two principles promise: the same policy, unmodified, should be able to run at two different enterprises with entirely different systems of record behind `VendorApproved`, because only the Knowledge layer's configuration differs.

**Runtime Authority should never retrieve enterprise data.** This is not merely an implementation preference; it is what preserves OPA's pure-function evaluation guarantee, which the rest of the platform's determinism, testability, and evidentiary replayability depend on. If Runtime Authority ever reached out mid-evaluation to fetch a fact, every guarantee currently made about reproducible bundle hashes and replayable decisions would need to be re-examined, because the same policy bundle evaluated twice against "the same" input could legitimately produce different results depending on what a live system said at each moment. Whatever Enterprise Knowledge Resolution turns out to be, its output to Runtime Authority must be a static, already-resolved value at the moment evaluation begins.

**Enterprise Knowledge should never perform authorization.** A resolver's job is strictly to answer "is X true, and how confident/fresh is that answer" — never "is this action allowed." Collapsing these two questions inside one component would silently move the platform's actual authorization logic outside the one place designed to reason about it deterministically and auditably, recreating — in a new layer — precisely the kind of boundary-blurring the platform has already had to reckon with elsewhere (an all-or-nothing admin credential that, by design, bypasses the RBAC layer entirely, rather than being cleanly subordinate to it, is a cautionary example of what happens when a supposedly-lower layer quietly acquires a higher layer's authority).

A few additional candidate principles, offered more tentatively, not yet as settled as the five above:

**An assertion that cannot be resolved is not the same as an assertion that resolved to false.** The temptation to treat "we couldn't check" as equivalent to "no" is real, and might even be the *safe* default in some contexts — but it is not the same fact, and collapsing the two destroys information a human reviewer or an auditor would want. (Expanded in Section 11.)

**A resolver's trust level is not binary and should never be treated as if it were.** The platform's own operator-key mechanism already demonstrates the failure mode of an all-or-nothing trust primitive; Enterprise Knowledge Resolution must not reintroduce the same anti-pattern one layer up, at a point where it would gate *what the platform believes to be true*, arguably a more consequential place for it to appear than where it exists today.

**Every resolved assertion should be independently auditable from the decision it fed.** An Evidence record proving a decision happened is necessary but not sufficient; whatever proves the assertion was actually true (or was honestly marked otherwise) is a separate, and separately valuable, artifact.

---

## 5. Business Assertions

A **business assertion** is a named, enterprise-scoped predicate representing something the business considers true or false (or partially known — see Section 11) about the world, independent of any single policy that might reference it and independent of any specific system that might currently back it.

Examples given in the originating discussion — `VendorApproved`, `AMLPassed`, `FraudCleared`, `BudgetAvailable`, `DelegationValid`, `ClaimEligible`, `InvoiceApproved` — share a common shape: each names a fact a *human* in the business would recognize and could explain, without any of them requiring the listener to know which system, table, or API would actually answer the question.

**Why assertions become reusable enterprise primitives.** In a large enterprise, the same underlying fact is almost never relevant to only one policy. `VendorApproved` plausibly matters to an invoice-payment policy, a purchase-order-approval policy, and a vendor-onboarding policy simultaneously. If each of those three policies independently decided how to check vendor approval, three things go wrong: the checks drift out of sync as systems change (one policy's integration gets updated, the other two don't), the enterprise's actual security/compliance posture becomes impossible to reason about as a whole (there is no single place to answer "how do we verify vendor approval, enterprise-wide"), and the integration work is triplicated for no benefit.

Treating an assertion as a single, named, shared enterprise primitive — resolved once per relevant decision, by one governed mechanism, regardless of which policy asked — is architecturally the same instinct Authority Intelligence already applies one layer earlier: a Principal or a Resource is a single graph node referenced by many relationships and many policies, not re-extracted and re-defined independently every time a document happens to mention it. Business assertions are a natural extension of that same idea, applied to the *conditions* under which policies act rather than the *entities* they act upon.

This reusability is also, plausibly, where much of the durable value in this layer would come from — a correctly-modeled, well-governed enterprise assertion vocabulary is closer to being infrastructure than it is to being a feature of any one policy (a theme returned to directly in Section 14).

---

## 6. Enterprise Knowledge Resolution

**What it does, at minimum:** given a decision-in-progress and the set of named business assertions the relevant policies reference, determine — for each — its current state (Section 11), with enough provenance to defend that determination later.

**What it should never do:**
- Perform authorization or evaluate policy logic (Section 4).
- Become the enterprise's system of record for the underlying business data. It should attest to or broker facts that live elsewhere, not replace SAP, Oracle, or Workday as the authoritative source — an assertion is a *claim about* the state of a system of record, not a competing copy of it.
- Silently synthesize a confident answer it cannot actually stand behind. A resolver that times out and defaults to "true" (or "false") because that was operationally convenient has committed the same category of error this whole layer exists to prevent, just one level further in.

**Where should organizational knowledge live?** This is genuinely open, and several models coexist as candidates rather than competing to be the one answer:

- Fully federated: Enterprise Knowledge Resolution holds no state of its own and queries the enterprise's own systems live, every time. No staleness risk from caching, but couples decision availability directly to the availability and speed of every backing system.
- A maintained knowledge cache/ledger: PayReality (or the deployment it runs in) keeps its own store of the most recently resolved value for each assertion, refreshed on some cadence or by event. Fast and available even during a source-system outage, but introduces the staleness question in full.
- A hybrid, assertion-type-dependent split: some assertions (financial thresholds, fraud checks) are always resolved live; others (vendor approval status, which changes rarely) are served from a cache with an explicit validity window.
- A fully external, push-based attestation model: the enterprise systems themselves push signed statements of fact to PayReality proactively, and "resolution" becomes verification of an already-received attestation rather than initiation of a query at all.

None of these is obviously correct in general, and the right answer plausibly differs by assertion type, by enterprise, and by how much the enterprise is willing to expose to a resolver versus keep entirely behind its own boundary. (Section 8 explores this same question from the resolution-mechanism angle in more depth.)

**How should it interact with Runtime Authority?** The one principle that seems firm (Section 4) is that the interaction must be strictly one-directional and must complete *before* Runtime Authority's evaluation begins — because OPA's evaluation model is a pure function over a static input document, there is no legitimate mechanism by which Runtime Authority could call back into Enterprise Knowledge Resolution mid-evaluation without abandoning the determinism guarantee the rest of the platform is built on. This is worth stating plainly as a *hard technical constraint already implied by an existing architectural choice* (using OPA/Rego for evaluation), not merely a preference invented for this new layer.

---

## 7. Runtime Intent

An AI agent's actual behavior is a tool call — a request to transfer money, update a record, send a document, provision access. The raw shape of that call is whatever the specific tool or API the agent is using happens to expect; it is not naturally expressed in the vocabulary Runtime Policy and Enterprise Knowledge Resolution need (a canonical action type, a canonical resource, a canonical set of assertions that action implicates).

Today, this translation already happens, informally: submitting an Intent for evaluation requires *someone* — the calling application, the SDK, the integrator — to have already mapped "what the agent is trying to do" onto action/resource/amount/context fields the platform understands. This works today because the space of actions is relatively small and each integration is bespoke and reviewed.

As AI agents gain access to more heterogeneous, more numerous, and more dynamically-discovered tools (arbitrary MCP-style tool catalogs, arbitrary third-party APIs an agent might be handed at runtime), the gap between "what the agent literally invoked" and "what canonical enterprise business action this represents" is likely to widen substantially. A payment tool, an ERP-write tool, and a workflow-approval tool built by three different vendors might all, in business terms, be "the same" action — but nothing today guarantees they'd be recognized as such.

**Should intent normalization become its own architectural capability?** Several positions are worth holding open simultaneously:

- **Keep it a thin, caller-side translation**, as today. Minimal new architecture, but pushes correctness entirely onto every integrator, and means the platform has no independent way to notice when two different tool calls are secretly the same business action (or when one tool call is secretly *two* business actions bundled together).
- **A dedicated Intent Normalization layer**, sitting before policy evaluation (and plausibly before or alongside Enterprise Knowledge Resolution, since knowing what assertions are implicated requires first knowing what canonical action is being attempted), whose job is mapping heterogeneous raw tool calls onto a canonical action taxonomy. This raises its own hard question: if this mapping is itself AI-assisted (which seems likely, given the diversity of possible tool shapes), does an LLM now sit somewhere in the authorization-adjacent path? That would be in real tension with the platform's existing "100% deterministic, no LLM anywhere in the authorization decision" principle — a tension this document flags explicitly rather than resolves, since it is exactly the kind of question a v0.1 document should surface rather than paper over.
- **Fold normalization into Authority Intelligence's existing vocabulary work.** Authority Intelligence already builds an operation taxonomy as part of the Authority Graph; a plausible position is that the *same* system that already owns "what operations exist in this enterprise's governance documents" should also own "what canonical action a given tool call maps to," treating both as facets of one enterprise action vocabulary rather than as two separate capabilities.

No position is adopted here. This is recorded as a genuinely open, and consequential, architectural question.

---

## 8. Assertion Resolution — Candidate Models

Several distinct mechanisms for actually resolving an assertion are worth naming individually, with their trade-offs, without selecting among them. In practice, a mature system will likely need several of these simultaneously, differentiated by assertion type — the harder governance question, explored more in Section 12, is *who decides* which model applies to which assertion, not which single model wins outright.

**Live lookup.** Query the source system directly, at the moment of decision. Freshest possible answer. Couples decision latency and decision *availability* to a third-party system's latency and availability — introducing a failure mode Runtime Authority does not currently have (a policy decision failing because SAP happens to be down, rather than because the policy itself denies the action).

**Cached assertions.** Resolve ahead of time, store the result with a validity window, serve from the cache at decision time. Fast, and available even when the source system is briefly unreachable. Introduces staleness risk as a first-class concern — and for a security-sensitive assertion like `FraudCleared`, "fast but possibly stale" may be an unacceptable trade for the assertion's whole purpose.

**Event-driven assertions.** The source system emits change events (a webhook, a message-bus event) whenever the underlying fact changes; PayReality's knowledge store is kept current by consuming these. Potentially very low resolution-time latency (the value is already current when needed, no query required), but depends on the source system supporting outbound events at all — not a given for many legacy enterprise systems — and introduces a completeness problem: how does the platform ever know it has actually received *every* relevant event, rather than silently missing one and holding a confidently-wrong cached value?

**Signed assertions.** The enterprise system itself cryptographically attests to a fact ("System X signs: VendorApproved=true for Vendor#123 as of timestamp T"), and PayReality verifies the signature rather than re-querying or holding standing credentials into the source system at all. Strong trust and data-minimization story — PayReality never needs to see the underlying record, only a signed claim about it — but requires the enterprise system (or something in front of it) to support signing infrastructure that essentially no legacy ERP has natively today. A real adoption barrier, not a technical dead end.

**Resolver plugins.** A pluggable resolution interface per assertion type or per system, authored and operated by PayReality, holding credentials directly into the customer's systems. Flexible and centrally maintainable, but means PayReality (or wherever its runtime executes) holds live credentials into a customer's core enterprise systems — a significant trust and blast-radius question any enterprise security team would rightly scrutinize closely.

**Enterprise adapters / knowledge connectors.** Similar in shape to a resolver plugin, but deployed and operated *inside the customer's own environment*, calling out to PayReality only with already-resolved assertions — never handing PayReality direct credentials into the customer's systems at all. This inverts the trust direction relative to a centrally-operated resolver plugin, at the cost of requiring the customer to deploy, run, and maintain infrastructure of their own.

These models differ most sharply along two axes worth naming explicitly, since they will likely recur every time a specific resolution mechanism is chosen for a specific assertion: **freshness vs. availability** (live lookup vs. caching), and **integration convenience vs. trust/blast-radius** (centrally-operated resolvers vs. customer-operated connectors, or signed attestation vs. direct query).

---

## 9. Data Residency

A closely related set of open questions concerns *what*, exactly, ever needs to cross into PayReality's boundary in order for an assertion to be resolved.

At least four distinct postures are worth holding side by side:

1. **Retrieve full enterprise records.** Highest utility (PayReality could, in principle, resolve nearly anything, and could show a human reviewer the underlying record for context) but the largest exposure and the hardest data-protection story — PayReality would now hold a copy of enterprise data it has no independent business need for beyond the single assertion it was resolving.
2. **Retrieve business assertions only.** A boolean, enum, or small structured value plus minimal provenance (which system, which record identifier, when) — much smaller data footprint, but PayReality still "knows" something about the customer's vendor, claimant, or transaction, and the provenance metadata itself may indirectly reference identifiable records.
3. **Retrieve signed assertions.** PayReality verifies a signature over a claim rather than computing the claim itself — PayReality never even derives the underlying fact from raw data, only confirms someone else already vouches for it.
4. **Retrieve cryptographic attestations more broadly** (e.g., proofs of a predicate without revealing the underlying value that satisfies it). The strongest data-minimization posture in principle — PayReality could prove "the amount is under the threshold" without ever seeing the amount — but the least mature fit for typical enterprise legacy-system integration today, and likely years away from being a practical default even if it becomes a real target.

**GDPR/POPIA implications.** An assertion's boolean value (`AMLPassed = true`) may not itself be personal data, but its provenance record almost certainly references something that is (a customer record ID, a transaction reference, a timestamp tied to a specific individual's activity). Data-minimization principles argue PayReality should retain the smallest artifact sufficient to defend a decision under audit — not the richest artifact that would be convenient for some future feature. This is a real, unresolved tension: an auditor five years from now may want more context than a minimized record preserves, while a privacy regulator today would want less than a rich record contains. This document does not resolve that tension; it names it as one the eventual design must confront directly, likely per-jurisdiction and possibly per-assertion-type.

**Enterprise security implications.** Every credential or standing connection PayReality holds into a customer's systems is a new blast radius, independent of how carefully it is used. The signed-assertion and customer-operated-connector models (Section 8) both reduce this specific risk at the cost of integration friction and adoption burden. This trade-off — security/exposure posture versus integration convenience — recurs throughout this entire layer and should be treated as a first-class comparison axis for any future concrete design, not an afterthought bolted onto whichever mechanism turns out to be easiest to build first.

**Multi-jurisdiction complexity.** A single enterprise customer operating across multiple jurisdictions may need the *same* assertion type resolved under different data-locality constraints depending on which jurisdiction the underlying record belongs to — raising the possibility that "how an assertion is resolved" may need to vary not just by assertion type or by customer, but by the specific record or transaction's own jurisdiction, a level of granularity this document has not attempted to design for, only to flag.

---

## 10. Runtime Performance

Runtime Authority today evaluates a decision against a compiled OPA bundle in a matter of milliseconds — evaluation is local, deterministic, and effectively free relative to anything involving a network call. Enterprise Knowledge Resolution, by contrast, may need to reach genuinely external, genuinely slow, genuinely sometimes-unavailable systems. This is a real architectural tension, not a tuning problem to be solved later.

**Latency budgets.** If an AI agent expects near-real-time authorization, and resolving even one assertion requires a round trip to a legacy on-premise system with its own authentication handshake and query latency, the end-to-end decision time could become orders of magnitude slower than anything Runtime Authority alone has ever had to sustain. Two broad postures follow from this, again not mutually exclusive: resolve assertions **ahead of** the time-critical moment wherever possible (caching, event-driven updates, pre-fetching against predicted future decisions), or accept explicitly that **some decisions genuinely cannot be made instantly**, and design a first-class "this is still being resolved" path into the decision model itself rather than forcing every decision to complete synchronously (this connects directly to the Pending/Retryable states in Section 11).

**How latency budgets might shape architecture.** It's plausible — though not established — that different assertion types warrant different default resolution strategies based on how time-sensitive the decisions that typically depend on them are: a small-value budget-availability check might reasonably tolerate a cached answer that's a few hours old; a fraud check on a large wire transfer plausibly should not. Whether this should be a property intrinsic to the assertion type, a property of the specific policy referencing it, or a property of the specific decision's own risk profile is not decided here — it is recorded as a design axis worth exploring, not a rule to enforce yet.

**Scaling to thousands of enterprise systems.** Authority Intelligence already applies a disciplined vendor-neutral abstraction above any single AI provider — a `Protocol` interface with several interchangeable implementations, none of which the layers above are allowed to know about directly. The natural instinct is that Enterprise Knowledge Resolution should generalize the same discipline: a vendor-neutral resolution abstraction above any single enterprise system. But the AI-provider space is small and slow-changing (a handful of viable providers); the enterprise-system space is enormous, heterogeneous, and often bespoke even within a single customer. It is a genuinely open question whether a small number of clean internal abstractions can actually cover "thousands of enterprise systems," or whether the honest shape of this problem is closer to an integration-marketplace model (in the way Zapier, MuleSoft, or Workato exist as whole platforms devoted to exactly this kind of heterogeneity) than to a clean internal interface PayReality could design and hold stable on its own. This should be recorded as unresolved and revisited directly once real integration attempts — even one or two — have been made, rather than assumed away in either direction.

---

## 11. Assertion States

A binary true/false model for assertions is almost certainly insufficient, for reasons implied throughout this document but worth stating together, as their own dedicated design space. Candidate states include:

- **Satisfied** — resolved, and true.
- **Unsatisfied** — resolved, and false.
- **Unknown** — no resolver has been configured for this assertion at all, or resolution has never been attempted.
- **Unavailable** — a resolver exists and is configured, but the source system could not be reached at the time resolution was attempted.
- **Expired** — was resolved at some point, but the result's validity window has since passed.
- **Pending** — resolution has been initiated (e.g., an asynchronous or human-mediated check) but has not yet completed.
- **Retryable** — a transient failure occurred; resolution is expected to succeed if attempted again.
- **Escalated** — resolution has been deliberately routed to a human, either because automatic resolution isn't possible for this assertion type or because the result carries insufficient confidence to act on automatically.

**How might Runtime Authority reason about these?** The Decision Engine already has a three-outcome model — Allow, Deny, Human-Review — and a natural, though not yet decided, instinct is that any assertion state other than a clean Satisfied or Unsatisfied should generally push the overall decision toward Human-Review rather than being silently coerced into a definite true or false. This would extend a pattern the platform already leans on: preferring an honest "we don't know, so a person should look" over a confident-but-unfounded automatic answer. Whether this should be a fixed platform-level rule, or itself something a policy author can configure per assertion (e.g., "if `BudgetAvailable` is Unavailable, deny by default; if `VendorApproved` is Unavailable, escalate"), is left open — both have real arguments in their favor, and a fixed global rule risks being wrong for cases a policy author would have handled differently if given the choice.

---

## 12. Enterprise Trust

Establishing that a resolved assertion can actually be trusted is a distinct problem from establishing the assertion's value at all, and deserves its own explicit treatment.

**How do we know a resolver is trustworthy?** This cannot sensibly be a single yes/no property, for the same reason the platform's existing all-or-nothing admin-credential mechanism has already proven to be a weak pattern where it exists today — a binary "trusted" bit, once thousands of resolvers or connectors potentially exist across many customers and many system types, would be a single point of both failure and abuse. A gradient — some notion of trust tier, certification, or track record — seems more likely to be needed, but exactly what that gradient measures (technical reliability? organizational accountability? cryptographic verifiability of its claims? some combination?) is unresolved.

**How do we know assertions are fresh?** Freshness could be **resolver-declared** (the resolver states its own validity window at the moment it answers) or **platform-inferred** (the platform notices a resolver has gone quiet longer than its historical reporting cadence would suggest, and independently marks its most recent outputs as suspect even if the resolver never said so itself). Both have merit and are not mutually exclusive; a resolver-declared TTL is simpler and puts the burden of honesty on the resolver, while platform-inferred staleness detection provides a check even against a resolver that fails silently rather than explicitly.

**How should stale knowledge be detected before it causes harm**, rather than merely after? This is closely related to the freshness question above but emphasizes prevention over labeling — is there value in a background process that proactively re-validates assertions nearing the edge of their validity window before they're actually needed for a decision, rather than discovering staleness only at the moment a decision is attempted? Left open.

**How should Evidence reference enterprise knowledge?** Evidence today cryptographically proves a decision happened and what it was. If Enterprise Knowledge Resolution exists, an audit five years from now asking "why was this allowed" will hit a wall exactly at this boundary unless Evidence also captures *which assertions, in what states, resolved by what mechanism, with what provenance* fed the decision. Whether Evidence should embed the resolved values directly, embed only a hash or reference to a separately-retained knowledge record, or something in between, is an open design question with the data-minimization tension from Section 9 folded directly back into it: richer Evidence is more useful for a future audit and more exposed as a stored artifact; leaner Evidence is safer to retain and less useful if a genuinely hard question is asked of it later.

---

## 13. Open Research Questions

This section is intentionally the largest in the document. Nothing here is meant to be answered by this version. Questions are grouped by theme for navigability, not by importance or sequence.

### Architecture & boundaries

- Is Enterprise Knowledge Resolution better modeled as a **pipeline stage** (as drawn in Section 3) that Runtime Policy hands off to and Runtime Authority receives from, or as a **consulted service** that both Runtime Policy authoring and Runtime Authority evaluation independently query — a directory rather than a conveyor belt? These have materially different implications for where state lives and how versioning/timing works.
- Given OPA's pure-function evaluation model, does *all* resolution have to complete strictly before evaluation begins, with no exceptions — or is there a legitimate case for a constrained, still-deterministic form of "resolution during evaluation" (e.g., OPA consulting a value that was itself pre-computed and frozen for this evaluation, versus OPA making a live call) that doesn't actually violate the determinism guarantee if scoped carefully enough? Is that distinction even meaningful, or is it a rationalization for reintroducing exactly the coupling Section 4 argues against?
- Is there a clean, principled line between "a business assertion resolved by Enterprise Knowledge Resolution" and "a Runtime Policy condition on a field already native to the Intent" (like `amount`) — or is this actually a spectrum, and if so, where on that spectrum does Runtime Policy's own authority end and Enterprise Knowledge Resolution's begin? Could a future field that today looks Intent-native (e.g., a "verified" currency conversion rate) eventually need its own resolution treatment?
- Should Enterprise Knowledge Resolution be one platform-operated capability, or a federation of independently-operated, per-customer, or even per-system resolvers coordinated by only a thin, mostly-passive layer PayReality operates centrally? What does "the platform" even mean in a fully federated version of this?

### Assertion modeling

- Should assertions remain strictly state-based (Section 11's enumerated states) or should some assertions carry richer structure — a confidence score, a numeric value evaluated against a threshold elsewhere, a structured object with sub-fields? Does allowing richness reopen exactly the "policies should express business truths, not retrieval details" principle from Section 4, if a policy now has to know how to interpret a resolver's structured output?
- Who owns the canonical vocabulary of assertion names across different enterprise customers? Is `VendorApproved` the same concept everywhere, or does each customer need the ability to define its own semantics for a similarly-named assertion — and if customization is allowed, how does the platform avoid recreating the exact fragmentation problem business assertions were meant to solve in the first place (Section 5)?
- Can assertions depend on other assertions (`ClaimEligible` depending on both `FraudCleared` and `BankVerified`)? If so, is that dependency graph structurally similar enough to the Authority Graph Authority Intelligence already builds that the same modeling and tooling could be reused — or is an assertion-dependency graph a fundamentally different kind of structure (e.g., because assertions can expire and authority relationships mostly don't) that deserves its own treatment?

### Resolution & trust

- What should happen when two resolvers, or two systems, disagree about the same assertion for the same subject? Is disagreement itself a state (distinct from Unknown), and if so, how would a human reviewer or Runtime Authority reasonably act on it?
- Should a resolver ever be permitted to retroactively change a past answer? If a vendor's approval is later revoked, does that change history, or does it only affect future resolutions — and if a past Evidence record already cited the old answer, what, if anything, needs to happen to that record?
- Is a marketplace model for third-party resolvers/connectors plausible, and if so, who certifies that a third-party resolver is trustworthy enough to feed decisions that Evidence will cryptographically vouch for — PayReality itself, the customer, an independent auditor, some layered combination, or a model not yet imagined?
- How should a *planned* system outage (a scheduled maintenance window an enterprise system operator has announced in advance) be treated differently, if at all, from an *unplanned* outage, given both produce the same technical symptom (an unreachable resolver) but arguably carry very different implications for how a decision should be handled in the meantime?

### Performance & scale

- Is there a single acceptable end-to-end latency budget for "a real-time AI action," or does this vary so much by industry and decision type that a single platform-wide target would be meaningless — and if it varies, should that variation be a property the platform models explicitly, or left entirely to each policy/customer to configure without platform opinion?
- Can speculative or predictive pre-resolution of assertions (resolving ahead of an anticipated future decision, before it's actually requested) ever be architecturally safe, given that a "recently pre-fetched but not resolved at the actual moment of decision" assertion is arguably exactly the staleness risk this whole layer exists to guard against? Or is there a principled way to bound how "ahead" pre-resolution is allowed to be that makes it safe in practice?
- At what point does building resolution coverage for "thousands of enterprise systems" functionally turn PayReality into an integration platform, in the sense that MuleSoft, Boomi, or Workato are integration platforms — and is that a direction PayReality should want to go, either technically or as a matter of what kind of company it is? Is there a middle path where PayReality defines the *interface* thousands of systems must be adapted to, without ever building or operating most of those adapters itself?

### Privacy, residency & compliance

- Can a genuinely useful assertion be resolved with literally zero enterprise data crossing into PayReality's own boundary — full local resolution, remote attestation only — for a meaningful majority of the assertion types real enterprises will actually need? Or is this an appealing ideal that only a small minority of assertion types will ever practically achieve, given how few legacy systems support the signing/attestation infrastructure this would require?
- How should the architecture handle a single customer with genuinely different data-locality requirements for the same assertion type across different jurisdictions it operates in — is this a per-deployment configuration question, a per-record routing question, or something that reveals the entire "one Enterprise Knowledge Resolution layer" framing needs to be jurisdiction-aware in a way this document hasn't yet considered?
- If PayReality relays a resolver's assertion that later turns out to have been wrong — not because PayReality malfunctioned, but because the underlying enterprise data was itself incorrect — what is PayReality's actual role and liability? Is PayReality simply a conduit with no independent duty of care over the truth of what it relays, or does the act of relaying (and cryptographically vouching for the fact that a decision relied on it) create some obligation beyond that? This is as much a legal/product question as an architectural one, but the architecture will need to be built with an answer in mind, even a provisional one.

### Evidence & audit

- Should an Evidence record be self-contained enough to stand on its own, years later, even if the enterprise system that originally supplied an assertion no longer exists, has been replaced, or has changed its own data since? If self-containment is a goal, what does that imply about how much of an assertion's substance must be captured at decision time rather than referenced externally — and does that conflict with the data-minimization instinct from Section 9?
- Does the audit trail need to visibly and permanently distinguish "this decision relied on a cleanly Satisfied assertion" from "this decision relied on an assertion that was Unknown/Unavailable and got escalated to a human, who then approved it"? If so, is that distinction part of Evidence itself, or does it belong to a separate but linked record — and either way, how should someone reviewing history tell the two apart at a glance, years later, without needing to reconstruct context that may no longer be readily available?

### Governance & product

- Within an enterprise customer's own organization, who should be authorized to define a new business assertion, or to change which resolver/mechanism backs an existing one? Is this naturally a Policy Administrator's concern (the same role that already governs Runtime Policy lifecycle), a distinct new role this layer would need to introduce, or something that varies so much by customer that the platform shouldn't prescribe an answer at all?
- Does Enterprise Knowledge Resolution need its own lifecycle — draft, review, approval, versioning, deprecation — analogous to what Runtime Policy already has? If it does, is that itself evidence that this is a **peer** architectural layer to Runtime Policy, deserving equivalent governance investment, rather than a subordinate service Runtime Policy merely calls out to?
- If assertions become genuinely reusable enterprise primitives (Section 5), should other consumers besides Runtime Authority — human approval workflows, legacy RPA tooling, conventional application business logic — eventually be allowed to ask "is `VendorApproved` true" directly, without going anywhere near an AI action or a policy decision at all? If so, this layer's actual customer, over time, may turn out not to be Runtime Authority specifically, but "anything in the enterprise that needs a governed business truth" — a possibility explored further, and deliberately left open, in Section 14.

---

## 14. Long-Term Vision (Explored, Not Concluded)

It is worth holding open — without deciding — whether Enterprise Knowledge Resolution eventually becomes something considerably larger than a service Runtime Authority happens to consult.

**As a foundational enterprise capability in its own right.** If business assertions genuinely become reusable, governed, enterprise-wide primitives (Section 5), it is plausible that an enterprise would want the ability to ask "is `VendorApproved` true" for reasons that have nothing to do with an AI agent or a policy decision at all — a human approval workflow, a legacy RPA process, or an ordinary application might all want the same governed, auditable answer to the same question. If that happens, this layer's real customer stops being "Runtime Authority" specifically and becomes "anything inside the enterprise that needs a trustworthy business truth" — a meaningfully broader mandate than the one it would have been built to serve.

**As a platform.** Rather than something PayReality builds and operates entirely itself, Enterprise Knowledge Resolution could become something third parties build resolvers, connectors, and integrations *on top of* — in the way OPA itself is a platform other systems (including PayReality) build policy on top of, one layer below where this document sits. Under this framing, PayReality's own value shifts from "we resolve your enterprise facts" to "we define, govern, and certify how enterprise facts get resolved, by whoever builds the resolver."

**As a runtime operating layer.** It is possible — though a much larger claim — that a reliable, governed, cross-system enterprise-truth layer becomes infrastructure other systems simply assume exists, the way an identity provider or DNS is assumed infrastructure today rather than a feature of any one vendor's product. This would place Enterprise Knowledge Resolution closer to something like an "enterprise fact directory" than a component of an AI-governance product specifically.

**As something larger than Runtime Authority itself.** Today, Runtime Authority is the platform's center of gravity, with Authority Intelligence and Evidence serving it. It is worth naming, explicitly and without endorsement, the possibility that the harder and more durable problem — reliably, freshly, and verifiably establishing what is *true* about an enterprise at any given moment — may turn out to be more valuable, more defensible, and more general-purpose than authorizing any one class of action (AI-driven or otherwise) against that truth. Under this framing, AI-action authorization becomes one consumer among several of a deeper capability, rather than the capability's reason for existing.

**None of this is concluded here.** Each of the four framings above carries real strategic and architectural weight, and each also carries real risk of scope creep, unclear ownership, or building infrastructure ahead of demonstrated need. This document's only claim is that the possibility is real enough to track deliberately as Enterprise Knowledge Resolution takes shape — revisited explicitly at each future milestone, not assumed either way by default.

---

## Document History & Evolution

**v0.1 (this version).** First articulation of the architectural problem, the candidate future pipeline, a starting set of principles, and a deliberately large open-questions section. No implementation decisions made or implied.

**Candidate triggers for a v0.2 revision** (recorded here so future authors know what would warrant updating this document, rather than starting a new one):

- A real enterprise customer articulates a concrete, specific assertion requirement (a named fact, a named source system, a stated freshness expectation) — the first genuine external signal against which this document's abstractions can be tested.
- A first resolver or connector prototype is built, of any kind, for any single assertion — even a throwaway one — since building even one will surface which of Section 8's models are actually tractable versus merely plausible on paper.
- A decision is reached, even tentatively, on the Runtime Intent / normalization question in Section 7 — because that decision has downstream implications for nearly every other open question in Sections 8 through 13.
- Any principle in Section 4 is found, in practice, to be violated by a real design under consideration — at which point the principle itself should be re-examined rather than quietly overridden.

This document should be treated as a living record of the organization's current best thinking, not a specification to build against. Its value is in the questions it keeps visibly open as much as in the structure it proposes.
