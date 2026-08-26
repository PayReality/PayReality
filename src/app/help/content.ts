// Single source of truth for every piece of Help Center content: the
// Learn glossary, the Getting Started checklist, Troubleshooting guides,
// Developer Resources, and Contact actions. Search (search.ts) and the
// contextual HelpIcon popovers both read from this same data so a term
// explained here can never drift from what the full Help panel says
// about it.

export interface LearnArticle {
  id: string;
  term: string;
  summary: string;
  body: string;
}

// Plain-English explanations of this platform's actual concepts, not
// generic SaaS boilerplate. Written for a non-technical enterprise buyer
// or operator, not a developer -- see DEVELOPER_RESOURCES below for the
// technical version of the same ideas.
export const LEARN_ARTICLES: LearnArticle[] = [
  {
    id: "runtime_authority",
    term: "Runtime Authority",
    summary: "The platform's core idea: checking every AI agent action against your rules the moment it happens, not after.",
    body: "Runtime Authority is what makes an AI agent's action safe to allow: instead of trusting an agent to behave correctly, every single action it tries to take is checked against your organisation's actual rules at the exact moment it happens. If the action matches an active rule, it's allowed. If it doesn't clearly match anything, it's never guessed at, it's sent to a human to decide. Nothing about this depends on the agent being well-behaved; the check happens outside the agent, every time, with no exceptions. This decision is what PayReality is responsible for. Whether an action is actually stopped depends on the systems your organisation connects to it: PayReality tells you what's authorised and preserves proof of the decision, and a system wired to require that answer can act on it, but PayReality reaching a decision is not, by itself, the same as an action being physically blocked. See Capability Authorization for how a decision can be handed to a downstream system in a way it can verify.",
  },
  {
    id: "runtime_policy",
    term: "Runtime Policy",
    summary: "A single, precise rule: who can do what, under which conditions, up to what limit.",
    body: "A Runtime Policy is one rule, written once and evaluated consistently every time it applies: which agent (acting on whose behalf), which action, under which conditions (amount limits, categories, timing), gets allowed, denied, or sent to a human for review. Every edit creates a new version rather than overwriting the old one, so you can always see exactly what a rule said at any point in time and who changed it. A rule only takes effect once it's reviewed, compiled, and published; a draft never silently governs a real action. A Runtime Policy is not the same thing as an Authority Graph finding: the graph is a proposed reading of your documents, still waiting for review; a Runtime Policy is what's actually live, and only after a person has reviewed and published it.",
  },
  {
    id: "authority_graph",
    term: "Authority Graph",
    summary: "The map of who can act, on whose behalf, over what, drawn automatically from your real documents.",
    body: "When you upload your governance documents (delegation of authority policies, approval matrices, procurement or HR policy), the AI Authority Builder reads them together and draws out the underlying structure: which roles exist, what they're allowed to do, what limits apply, and where two documents disagree with each other. That structure is the Authority Graph. It's never published automatically, every finding is a reviewable claim, cited back to the exact document and location it came from, until a person promotes it into an actual Runtime Policy.",
  },
  {
    id: "authority_freshness",
    term: "Authority Freshness",
    summary: "Delegated authority can go stale. This is how PayReality tracks whether a rule still reflects who's actually accountable, and what happens if it doesn't.",
    body: "A Runtime Policy is only as good as the real-world delegation it's based on. People change roles, budgets get reset each year, and a delegation that was correct six months ago might not be anymore. Authority Freshness tracks that, separately from whether the rule itself works. Every rule can have a last attestation date (when someone last confirmed it's still correct), a review cadence (how often it should be re-checked), and a next review date calculated from those two. When that next review date passes, the rule is marked Review Due. This is a reminder, nothing more: a Review Due rule keeps being evaluated exactly as before, and still allows, denies, or escalates actions the same way it always did. It is only a signal to a human that it's time to reconfirm the delegation is still accurate, through re-attestation: a governance reviewer looks at the rule again and confirms it, which resets the clock. Authority Expired is a different, stronger state, and the two are never shown as the same thing. A small number of rules, specifically ones marked high or critical risk, can be configured so that if their authority genuinely expires (not just becomes due for review, but passes a hard expiry date with no re-attestation), any action that would otherwise be Allowed is instead sent to Human Review until someone re-attests. Lower-risk rules that go unreviewed do not get this automatic escalation; that's a deliberate, disclosed trade-off, not an oversight. Review Due and Authority Expired are always shown separately, on purpose: one is a reminder, the other can genuinely change what happens to a real action. Re-attesting (sometimes written \"reattest\") is the only way to clear either a review-due reminder or a genuinely expired authority state.",
  },
  {
    id: "agent_certificate",
    term: "Agent Certificate",
    summary: "An AI agent's cryptographic ID card: proof it really is who it says it is.",
    body: "Every registered AI agent gets its own certificate, tied to a private key only that agent holds. Every action it submits is signed with that key, so the platform can verify the request genuinely came from that specific agent and hasn't been tampered with in transit. If an agent is compromised or decommissioned, its certificate is rotated or revoked, immediately cutting off its ability to act, the same way you'd deactivate an employee's access badge.",
  },
  {
    id: "ai_authority_builder",
    term: "AI Authority Builder",
    summary: "Reads your real governance documents and drafts the rules for you, instead of you writing them by hand.",
    body: "Most organisations already have their delegation-of-authority policy written down somewhere, a PDF, a policy manual, a spreadsheet of approval limits. The AI Authority Builder reads those documents (as many as you have, together, so it can catch contradictions between them) and proposes the Authority Graph and candidate rules for you to review. You never have to translate your existing policy into rule-writing syntax by hand; you review what it found, and promote what's correct.",
  },
  {
    id: "runtime_decision",
    term: "Runtime Decision",
    summary: "The actual outcome when an agent tries to act: allowed, denied, or sent to a human.",
    body: "A Runtime Decision is the record of one specific moment: an agent tried to do something, and Runtime Authority checked it against the authority your organisation already delegated, using whatever rules and enterprise facts were relevant at that exact time. There are exactly three outcomes: Allow (it matched an active rule cleanly), Deny (a rule explicitly forbids it, or nothing authorises it), or Human Review (nothing clearly matched, so a person decides rather than the system guessing). This is deliberate: if the platform is ever genuinely unsure, it never defaults to Allow. Every decision, regardless of outcome, produces its own signed Evidence record. A decision proves that a request was evaluated against a specific, named rule at a specific moment, and what the outcome was. It does not, on its own, prove that an Allow decision was actually acted on afterward; see Capability Authorization for how that boundary works.",
  },
  {
    id: "human_review",
    term: "Human Review & Approvals",
    summary: "Human Review and policy approval are two different things that both involve a person saying yes. Here's the difference.",
    body: "PayReality involves a human reviewer in two genuinely different situations, and it's easy to confuse them because both get called \"review\" or \"approval\" in everyday language. The first is decision-level Human Review: an AI agent's real action was evaluated, and Runtime Authority couldn't clearly match it to an Allow or a Deny, so it was sent to a person to resolve rather than the system guessing. That resolved decision (approved or rejected, with a reason) becomes part of that decision's own Evidence, permanently. Note that resolving it never changes the original decision itself, which stays recorded as Human Review forever; the resolution is kept as its own separate, permanent fact layered on top, so both \"what Runtime Authority originally decided\" and \"what a person later decided\" stay visible rather than one overwriting the other. The second is policy-level review and approval: before a Runtime Policy is ever published and starts governing real actions, it goes through its own separate authoring workflow, drafted, submitted for review, and approved or rejected, entirely independent of any specific agent action. A policy being \"in review\" has nothing to do with any particular decision being stuck; it means a rule itself hasn't been published yet. If you're looking for decisions waiting on a person to resolve, that's the Pending Review Queue. If you're looking for policy drafts waiting on approval before they can be published, that's inside Governance, on the policy's own page.\n\nWhat happens on the AI agent's side while it waits? The agent (or whatever system submitted the request on its behalf) doesn't have to sit there doing nothing, and it doesn't get tapped on the shoulder the moment someone resolves it either. It's expected to check back for the outcome, either right after a person resolves it, or the next time it happens to look, even if that's after a restart, so it can pick up right where it left off. Either way, nothing about the underlying decision changes because of when it happened to check; a resolution that already happened is simply waiting to be read whenever it asks.",
  },
  {
    id: "trusted_enterprise_facts",
    term: "Trusted Enterprise Facts",
    summary: "Sometimes PayReality needs to know something from another enterprise system before it can decide whether an action is authorised, and it can't simply take the AI agent's word for it.",
    body: "Sometimes authority depends on something outside the request itself. An AI agent might propose paying a supplier invoice for a specific amount, but the rule governing that payment might also require that the supplier is approved (a \"supplier approved\" fact), or that a purchase order actually exists. The same mechanism works for non-financial actions too: a rule governing when an account may be disabled might require an \"account privileged\" fact from your identity system, not a dollar figure. The agent making the request should not be trusted to simply assert that on its own; an agent that's compromised, confused, or just wrong could claim anything. Instead, PayReality can check a Trusted Enterprise Fact: a piece of information asserted by a separate, registered source your organisation has explicitly trusted for that purpose, cryptographically signed so PayReality can tell it genuinely came from that source and hasn't been altered. Every fact has an expiry; nothing is trusted indefinitely. If a fact a rule depends on is missing, has expired, or if two trusted sources disagree about it, PayReality does not guess: the condition simply isn't satisfied, the same as any other unmet condition, and the decision fails closed rather than assuming the best case. Exactly which fact was checked, its value, its source, and how fresh it was at the time are all recorded on the decision's Evidence, so the reasoning behind a decision that depended on a fact can always be reconstructed later. One important boundary: a Trusted Enterprise Fact proves what an authenticated source asserted, and that this specific assertion was used in this specific decision. It does not prove that the assertion is objectively true; if the registered source itself were wrong or compromised, PayReality would still be evaluating in good faith against what it was told. Today, finding out exactly which fact was missing or unclear behind a specific decision is something your platform administrator or technical team can look into directly; it isn't yet something every user can inspect on screen.",
  },
  {
    id: "evidence",
    term: "Evidence",
    summary: "A signed, unchangeable record of exactly what was decided, and why, proof you can hand to an auditor.",
    body: "Every action Runtime Authority evaluates produces an Evidence record: what was requested, which of your organisation's rules applied, which exact version of that rule was active at the time, and what the outcome was. Each record is cryptographically signed, and each new record is linked to the one immediately before it, so a record can't be quietly altered, deleted, or reordered afterward without that tampering being detectable, not by this platform, not by anyone. An auditor, insurer, or regulator can verify a piece of Evidence independently, without having to trust this system's own word for it. If a decision also relied on a Trusted Enterprise Fact, that fact (its value, its source, and how fresh it was) is recorded on the same Evidence too, so you can see exactly what information the decision was based on. What Evidence does not prove: it proves a decision was made, under a specific policy version, at a specific moment, and, where relevant, what Capability Authorization was later issued and consumed for it. It does not, by itself, prove that the underlying business action, the actual payment, the actual system update, genuinely completed out in the real world; that is a separate question from the decision itself. Evidence is also not the same thing as an ordinary system log or telemetry: a log is a note a system keeps about itself and can typically be edited or deleted by whoever administers that system; Evidence is sealed at the moment it's created, and its integrity can be checked by someone with no access to this platform at all.",
  },
  {
    id: "capability_authorization",
    term: "Capability Authorization",
    summary: "For an Allow decision, PayReality can issue a short-lived, signed authorisation (sometimes called a capability token) that a downstream system can check before letting the action proceed. It is not, by itself, what stops the action.",
    body: "Once Runtime Authority reaches an Allow decision, that decision needs to reach whatever system is actually going to carry out the action, an ERP, a payment rail, an identity system, an internal tool. Simply saying \"PayReality said yes earlier\" is weak: it doesn't prove which exact decision, for which exact parameters, or when it stops being valid. A Capability Authorization, sometimes called a capability token, is a signed, short-lived authorisation tied specifically to that one decision: which principal, which action, which resource, which constraints (an exact amount for a payment; an environment and account for a Security-Agent authorised to disable a privileged production account), which audience (which downstream system it's valid for), and a short expiry window, not an indefinite one. It can only be used once; presenting it again after it's been consumed, or presenting it to a system it wasn't issued for, is rejected. A downstream system can verify a Capability Authorization and, if it chooses to, refuse to let execution proceed without a valid one. This is an important and deliberate boundary: Capability Authorization is not itself enforcement, and PayReality is not currently what's called a Policy Enforcement Point, a system that itself sits in the way of an action and can physically stop it. PayReality decides and can issue this signed authorisation; it is the responsibility of the enterprise system on the other end to actually require it before letting the action happen. If a downstream system chose to ignore the authorisation entirely and execute anyway, PayReality has no way to physically prevent that today. What is real and verifiable is that a capability was issued for a specific decision, and whether it was later verified and consumed. What that does not prove is that the underlying business action, the actual payment, the actual system update, genuinely completed afterward; consuming the authorisation and completing the real-world action are two different things.",
  },
  {
    id: "assurance",
    term: "Assurance",
    summary: "The at-a-glance view of whether your governance is actually working the way you think it is.",
    body: "Assurance is where you see whether your organisation's delegated authority is actually being evaluated the way you expect: how many actions were within delegated authority, how many were escalated to a human, how many fell outside it, and whether the underlying decision engine itself (the rule checker, the signing system, the database) is healthy. It's built for the person who needs the summary, not the detail underneath it.",
  },
  {
    id: "roles_and_permissions",
    term: "Roles & Permissions",
    summary: "Different people at your organisation need to do different things in PayReality. Roles control what each signed-in user can see and do.",
    body: "Not everyone who uses PayReality should be able to do everything in it. A Reviewer approving a policy shouldn't necessarily be the same person who can register a new AI agent, and someone auditing decisions after the fact shouldn't need the ability to change a rule. PayReality assigns every signed-in user a role (for example Governance Admin, Agent Admin, Reviewer, Auditor, or Executive, alongside an Owner role with full control), and that role determines exactly which actions and pages are available to them. A Governance Admin can author, approve, and publish Runtime Policies and resolve decisions. An Agent Admin can register, activate, suspend, and retire AI agents. A Reviewer can review and resolve decisions but cannot publish policies. An Auditor can see policies, decisions, evidence, and agents, but cannot change anything. An Executive sees the Assurance summary only. If a button looks disabled, or you can't access a page or action you expected to, that is almost always your role, not a fault: the platform is intentionally not letting you take an action your organisation hasn't assigned to you. If you believe you should have a different set of permissions, the right next step is to ask your organisation's Owner or Governance Admin to review your role in Organisation Settings, not to look for a workaround.",
  },
  {
    id: "integrations_and_developer_access",
    term: "Integrating AI Systems with PayReality",
    summary: "What it actually means for an AI system to be \"connected\" to PayReality, and what's available today versus still coming.",
    body: "For an AI agent to be governed by PayReality at all, your engineering team registers it, giving it its own cryptographic identity, and has it sign every real action it proposes before submitting it. PayReality checks that signature, evaluates the request against your organisation's Runtime Policies and any relevant Trusted Enterprise Facts, and returns a decision along with signed Evidence. That is the whole integration contract from PayReality's side: register an identity, sign requests, receive decisions and evidence. What PayReality does not do today is reach into your enterprise systems and execute anything itself, or maintain a live, continuous connection watching everything an agent does; every check happens at the moment a specific action is proposed. Some capabilities described elsewhere in this Help Center, like a downstream system requiring a Capability Authorization before it acts, describe a boundary your own systems can be built to respect; PayReality does not build or manage that connector for you. The Developer tab in this Help Center links to the current, real API and SDK documentation for your engineering team; anything shown on the main website as \"Coming Soon\" is a genuine future direction, not something already available to integrate against.",
  },
];

export interface GettingStartedStep {
  id: string;
  label: string;
  description: string;
  path: string;
}

export const GETTING_STARTED_STEPS: GettingStartedStep[] = [
  {
    id: "import_governance",
    label: "Import Governance",
    description: "Upload your existing policy documents so the AI Authority Builder can draft your rules for you.",
    path: "/governance/authority-builder",
  },
  {
    id: "review_ai_findings",
    label: "Review AI Findings",
    description: "Check what the AI found in your documents before anything becomes a real rule.",
    path: "/governance/authority-builder",
  },
  {
    id: "publish_runtime_policies",
    label: "Publish Runtime Policies",
    description: "Approve and publish your rules so they start actually governing agent actions.",
    path: "/governance",
  },
  {
    id: "register_agent",
    label: "Register an Agent",
    description: "Give an AI agent its own identity and certificate so it can act under your rules.",
    path: "/agents",
  },
  {
    id: "submit_test_decision",
    label: "Submit a Test Decision",
    description: "Try a real action and watch it get checked against your rules in real time.",
    path: "/decisions",
  },
  {
    id: "review_evidence",
    label: "Review Evidence",
    description: "See the signed, tamper-evident record your test decision just produced.",
    path: "/evidence",
  },
];

export interface TroubleshootingGuide {
  id: string;
  issue: string;
  explanation: string;
  steps: string[];
  path?: string;
}

export const TROUBLESHOOTING_GUIDES: TroubleshootingGuide[] = [
  {
    id: "agent_not_appearing",
    issue: "Agent not appearing",
    explanation: "A newly registered agent doesn't show up in the Agent directory, or a status change hasn't shown up yet.",
    steps: [
      "Refresh the Agents page -- registration succeeds immediately, but the list doesn't auto-refresh while you're viewing it.",
      "Check the filters at the top of the Agents page (status, environment, owner, search) -- a filter left set from an earlier search will hide agents that don't match it.",
      "Confirm registration actually succeeded: a failed registration shows an error message rather than silently doing nothing.",
    ],
    path: "/agents",
  },
  {
    id: "signature_verification_failed",
    issue: "Signature verification failed",
    explanation: "An action was rejected because the cryptographic signature attached to it didn't check out.",
    steps: [
      "Confirm the agent is using its current, active certificate -- a signature made with a rotated or revoked key will always fail.",
      "Check the request's timestamp: signed requests are only valid for a short window (a few minutes) to prevent an old, captured request from being replayed later.",
      "If the agent's certificate was recently rotated, make sure the new private key generated on that rotation is the one actually being used to sign.",
    ],
    path: "/agents",
  },
  {
    id: "policy_wont_publish",
    issue: "Policy won't publish",
    explanation: "A rule is stuck and won't move to Published no matter what you try.",
    steps: [
      "Check the rule's status: it must be compiled successfully before it can be published -- an unresolved compile error blocks publishing entirely.",
      "If the rule was edited after it was last compiled, compile it again -- publishing intentionally refuses to deploy a bundle that's out of date with the rule's current content.",
      "Look for a specific compiler error message on the Publish page -- it names exactly what's wrong (an unsupported condition, an invalid value) rather than failing silently.",
    ],
    path: "/governance",
  },
  {
    id: "ai_extraction_incomplete",
    issue: "AI extraction incomplete",
    explanation: "An uploaded document didn't fully extract, or came back with unanswered questions.",
    steps: [
      "Check whether extraction actually failed versus simply raised clarification questions -- the two look different: a failure shows an error and lets you retry; questions are a normal part of review, not a failure.",
      "Answer any open questions on the corpus's review page -- some findings can't be finalized until you clarify an ambiguity the documents themselves didn't resolve.",
      "If extraction failed outright, the original document is still safely stored -- you can retry extraction without re-uploading.",
    ],
    path: "/governance/authority-builder",
  },
  {
    id: "decision_denied",
    issue: "Decision denied",
    explanation: "A test (or real) decision came back Denied instead of Approved, and it's not obvious why denied is the outcome you got.",
    steps: [
      "Denied means a rule explicitly forbids this action -- it's not an error, it's the platform doing exactly what it's supposed to do.",
      "Check the decision's reason: it names which rule or condition caused the denial, in plain language, not a raw error code.",
      "If you expected this to be allowed, check whether the right rule is actually published and active for this agent's principal -- a rule still in draft never governs a real decision.",
    ],
    path: "/decisions",
  },
  {
    id: "ai_features_unavailable",
    issue: "AI features showing sample data instead of your real documents",
    explanation: "The AI Authority Builder or AI Policy Builder is showing illustrative sample output instead of analyzing your real documents.",
    steps: [
      "This means no AI provider is currently configured on this deployment (this platform supports either Azure AI Foundry or an Anthropic API key). The platform tells you this directly via a banner rather than quietly returning fake results as if they were real.",
      "Everything you see in that state is sample data meant to show you what the feature does, not a real analysis of your uploaded document.",
      "This is a deployment configuration matter for whoever manages your hosting environment, not something fixable from within the product itself.",
    ],
  },
  {
    id: "permission_denied",
    issue: "I don't have permission to do this",
    explanation: "A button is disabled, or an action fails, specifically because of your role, not because anything is broken.",
    steps: [
      "Check what your assigned role actually covers. See Roles & Permissions in the Learn tab for what each role can and cannot do.",
      "A disabled button is usually intentional: the platform is refusing an action your organisation hasn't assigned to your role, not malfunctioning.",
      "If you genuinely need this permission, ask your organisation's Owner or a Governance Admin to review your role under Organisation Settings; changing your own permissions isn't something any role can do for itself.",
    ],
    path: "/organization",
  },
  {
    id: "authority_review_due_or_expired",
    issue: "A policy shows \"Review Due\" or \"Authority Expired\"",
    explanation: "A Runtime Policy's authority freshness has lapsed, and it's not obvious what that actually changes.",
    steps: [
      "Review Due is only a reminder: the policy keeps being evaluated exactly as before, nothing about how it decides real actions has changed yet.",
      "Authority Expired is stronger, but only matters for high or critical risk policies: for those specifically, an Allow that would otherwise happen is instead sent to Human Review until someone re-attests.",
      "To clear either state, a governance reviewer needs to re-attest the policy from the policy's own dashboard, confirming the underlying delegation is still accurate.",
      "See Authority Freshness in the Learn tab for the full explanation of why this exists.",
    ],
    path: "/governance/dashboard",
  },
  {
    id: "decision_requires_human_review",
    issue: "A decision is waiting on Human Review",
    explanation: "An agent's action didn't clearly match Allow or Deny, so a person needs to resolve it.",
    steps: [
      "This is not an error. It means Runtime Authority genuinely couldn't determine the outcome from your active rules, so it deliberately asked a person rather than guessing.",
      "Go to the Pending Review Queue to see every decision currently waiting, and approve or reject each one with a reason.",
      "Once resolved, that decision's outcome and your reasoning become a permanent part of its Evidence record; it cannot be silently changed afterward.",
    ],
    path: "/decisions/queue",
  },
  {
    id: "evidence_verification_failed",
    issue: "Evidence signature verification failed",
    explanation: "Checking a piece of Evidence came back \"Tampered or corrupted\" instead of confirming it's valid.",
    steps: [
      "Treat this as a real, urgent signal, not a glitch to retry and ignore. A genuine signature failure means that specific record's integrity can no longer be confirmed.",
      "Do not assume it's a false alarm. Escalate to your security or platform administration team immediately so the record, and how this happened, can be investigated.",
      "This is different from a decision outcome of Deny: this is about whether the record itself can still be trusted, not about what the original decision was.",
    ],
    path: "/evidence",
  },
  {
    id: "required_enterprise_information_unavailable",
    issue: "A decision was denied or escalated over enterprise information PayReality couldn't confirm",
    explanation: "A rule depended on a Trusted Enterprise Fact (like a supplier being approved) that was missing, expired, or contradicted by another source.",
    steps: [
      "This is fail-closed behaviour working as intended, not a bug: PayReality never guesses at missing or unclear information in your organisation's favour.",
      "Check the decision's stated reason; it names the condition that wasn't satisfied.",
      "Finding out exactly which fact was missing or stale currently requires your platform administrator or technical team to look into it directly; this isn't yet something every user can inspect on screen.",
      "See Trusted Enterprise Facts in the Learn tab for why this exists and how it's designed to fail safe.",
    ],
    path: "/decisions",
  },
];

export interface DeveloperResource {
  id: string;
  label: string;
  description: string;
  href: string;
}

// Canonical apex domain, no "www": every other file in both this
// repository and the marketing website repo uses this exact form
// (src/app/lib/site.ts's SITE_URL). "www.aisecurewatch.com" resolves
// today, but there is no reason for this one file to be the sole place
// depending on that redirect staying configured.
const WEBSITE_URL = "https://aisecurewatch.com";

export const DEVELOPER_RESOURCES: DeveloperResource[] = [
  {
    id: "api_docs",
    label: "API Documentation",
    description: "The full, interactive API reference for this deployment, generated directly from the running backend.",
    href: `${import.meta.env.VITE_API_URL ?? "/api"}/docs`,
  },
  {
    id: "sdk_docs",
    label: "SDK Documentation",
    description: "How to integrate an AI agent using the Python SDK: registration, signing, and lifecycle actions.",
    href: `${WEBSITE_URL}/developers/sdks`,
  },
  {
    id: "integration_examples",
    label: "Integration Examples",
    description: "Worked examples of registering an agent and submitting a signed decision end to end.",
    href: `${WEBSITE_URL}/developers/integration-examples`,
  },
  {
    id: "authentication",
    label: "Authentication",
    description: "How requests are authenticated: the Operator Key, per-developer API keys, and agent certificates.",
    href: `${WEBSITE_URL}/developers/authentication`,
  },
  {
    id: "agent_registration",
    label: "Agent Registration",
    description: "The full agent lifecycle: registration, activation, suspension, rotation, and retirement.",
    href: `${WEBSITE_URL}/developers/agent-registration`,
  },
];

export interface ContactAction {
  id: string;
  label: string;
  description: string;
  href: string;
}

export const CONTACT_ACTIONS: ContactAction[] = [
  {
    id: "report_bug",
    label: "Report Bug",
    description: "Something isn't working the way it should.",
    href: "mailto:sean@aisecurewatch.com?subject=" + encodeURIComponent("Bug report"),
  },
  {
    id: "feature_request",
    label: "Feature Request",
    description: "Something you wish the platform could do.",
    href: "mailto:sean@aisecurewatch.com?subject=" + encodeURIComponent("Feature request"),
  },
  {
    id: "contact_support",
    label: "Contact Support",
    description: "Talk to a person directly.",
    href: "mailto:sean@aisecurewatch.com",
  },
  {
    id: "documentation",
    label: "Documentation",
    description: "The full set of developer documentation for this platform.",
    href: `${WEBSITE_URL}/developers`,
  },
  {
    id: "system_status",
    label: "System Status",
    description: "Whether the platform is healthy right now.",
    href: "/organization",
  },
];
