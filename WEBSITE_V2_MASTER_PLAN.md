# Website V2 Master Plan

**Framing, stated plainly up front**: this is not a rebuild. The positioning audit (`PRODUCT_POSITIONING_REVIEW.md`) found the site's existing structure, navigation, and message discipline (its active avoidance of "AI governance platform" and similar generic language) already sound and mostly accurate. "Website V2" here means: correct the one significant factual error found, fill the specific gaps the audit named, and restructure content to reflect what Milestones 1-7 actually shipped, not a ground-up redesign for aesthetics, exactly as Phase 2 itself instructs.

## What stays exactly as it is

The current five-pillar structure (Platform, Products, Developers, Solutions, Company/Resources), the product page set (Runtime Authority, Authority Graph, Runtime Policies, Evidence Portal, Authorization Receipts), the disciplined refusal to call this an "AI governance platform," the honest "Coming Soon" labeling on unshipped features (Authorization Receipts, Webhooks, named integration connectors), and the candid founder/team-size/no-certification disclosures, all of these are working correctly and should not be disturbed by this milestone.

## What changes

### 1. The Rust/gRPC correction (highest priority, pending the decision `PRODUCT_POSITIONING_REVIEW.md` flags)

If confirmed as an error (this plan's own strong expectation, given seven milestones of direct, contradicting engineering evidence): replace every instance ("core runtime written in Rust," "communication runs over gRPC") across `products/RuntimeAuthority.tsx`, both founder bio pages, `Leadership.tsx`, and `index.html`'s JSON-LD, with the real, equally credible stack: Python (FastAPI) for the API layer, real Open Policy Agent evaluating compiled Rego for every decision, HTTP/JSON for agent-to-runtime communication. This is not a weaker story: "we evaluate every decision with the same open-source policy engine used in production infrastructure and Kubernetes clusters industry-wide" is a stronger, more verifiable claim than an unverifiable Rust/gRPC assertion, precisely because OPA is a known, respected, independently-auditable dependency a technical evaluator can go look up themselves.

### 2. New content for real, shipped, currently-undescribed capability

Per the Missing section of the positioning review:

- **A new "Enterprise Integrations" section** (Phase 2's own required structure names this explicitly): multi-tenancy and Enterprise Surface Isolation, described concretely (organization-scoped data at every layer: Postgres, OPA packages, Blob Storage, Azure AI Search), with the real second-organization isolation test from Milestone 5 as the specific, provable claim, not a generic "your data is safe with us."
- **An expanded Architecture section**: name the real Azure production topology (Container Apps, Postgres Flexible Server, Key Vault, Managed Identity, AI Foundry, AI Search), identity-first throughout, live on a real custom domain and certificate as of Milestone 7. State this in present tense; it is not aspirational.
- **A Runtime Policy Simulator mention** on the Runtime Policies product page: a real, working, saved-scenario-and-batch-CSV capability, demoable live.
- **An Evidence chain/signing-key-rotation mention** on the Evidence Portal page: the hash-chain-across-decisions property and the signing-key registry, both real, both a direct answer to "what happens if a key is ever compromised," a question any serious enterprise security reviewer will ask.
- **Correct the Authority Intelligence / AI Foundry framing**: the site currently only lists Azure AI Foundry as a future customer-facing "Coming Soon" integration. Add the separate, already-true, stronger claim: PayReality's own Authority Intelligence extraction pipeline already runs on Azure AI Foundry today, proven via a real, live extraction in Milestone 6.

### 3. Security page update

Per the Outdated finding: replace the "single shared operator credential, not yet scoped per-user" limitation with the current, real model (six-role RBAC for ordinary access, the operator credential reserved for genuine platform-admin actions only). This is a case where telling the truth makes the platform look *better* than the current copy does, worth prioritizing precisely for that reason.

## Structure (per Phase 2's required section list, mapped to what already exists or needs to be added)

| Required section | Status | Action |
|---|---|---|
| Hero | Exists (`Home.tsx`) | No change needed; already leads with the pre-execution/deterministic/cryptographic framing |
| Problem | Exists (`WhyWeExist.tsx`, `Manifesto.tsx`) | No structural change; already well-differentiated from "AI governance" |
| Runtime Authority | Exists (`products/RuntimeAuthority.tsx`) | Apply the Rust/gRPC correction |
| Authority Intelligence | Partially exists (folded into Authority Graph messaging) | Add the Azure AI Foundry "already live" claim named above |
| Architecture | Exists as developer content (`developers/Architecture.tsx`) | Expand with the real Azure topology; consider surfacing a lighter version for the non-developer Platform page too |
| Enterprise Integrations | **Missing as a named section** | New: multi-tenancy/isolation content, named above |
| Security | Exists (`Security.tsx`) | Apply the Outdated-finding update above |
| Evidence | Exists (`products/EvidencePortal.tsx`) | Add chain/signing-key-rotation content |
| Use Cases | Exists (`solutions/*`, eight industry pages) | No structural change |
| SDK | Exists (`developers/Sdks.tsx`) | No change; Python-only, planned-languages-disclosed framing is already correct |
| Pilot Program | **Missing** | New: a page built directly from `PILOT_PROGRAM_GUIDE.md`'s own stages (Qualification through Expansion), the first time this process is stated publicly rather than only internally |
| Company | Exists (`About.tsx`, `Leadership.tsx`, founder bios) | Apply the Rust/gRPC correction in the two founder bios specifically |
| Contact | Exists (`Contact.tsx`, the Book a Demo modal) | See the CTA-reliability finding below |

## A finding worth surfacing here even though it's not a Phase 1 content-accuracy issue

The site's primary conversion mechanism, "Book a Demo," is a `mailto:` link with no backend and no delivery confirmation (confirmed directly in the website audit): the visitor's email client opens with a pre-filled draft, and the confirmation screen shows regardless of whether the visitor's mail client is even configured or whether they actually hit send. As this milestone's own Launch Readiness Report states the platform is now ready to begin real pilot conversations, this mechanism becomes a real, practical risk: a genuinely interested enterprise prospect can silently fail to reach anyone. **PROPOSED**: replace the `mailto:`-only path with a real form submission (even a simple one, a serverless form handler or a lightweight CRM webhook) before actively driving pilot traffic to the site, since this milestone's whole purpose is making the company ready to receive real enterprise interest, not just describe the product accurately to it.

## Diagrams

See `SALES_ENABLEMENT_PACK.md`'s Architecture Deck section for the request-flow, Authority Intelligence, and Azure-topology diagrams; the website's own Architecture and Platform pages should adapt simplified, non-technical versions of the same three diagrams rather than inventing separate ones, so the public site and the sales deck never tell two different structural stories.

## What this plan does not do

It does not rewrite the site's voice, tone, or five-pillar navigation, which the positioning audit found sound. It does not add features to the actual product, per this milestone's own rule. It does not apply the Rust/gRPC correction unilaterally in this pass, since that correction, unlike the two README fixes already applied directly, touches founder-attributed quotes across five files and machine-readable structured data, and deserves an explicit go-ahead before five separate pieces of public, attributed copy change.
