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
    body: "Runtime Authority is what makes an AI agent's action safe to allow: instead of trusting an agent to behave correctly, every single action it tries to take is checked against your organisation's actual rules at the exact moment it happens. If the action matches an active rule, it's allowed. If it doesn't clearly match anything, it's never guessed at -- it's sent to a human to decide. Nothing about this depends on the agent being well-behaved; the check happens outside the agent, every time, with no exceptions.",
  },
  {
    id: "runtime_policy",
    term: "Runtime Policy",
    summary: "A single, precise rule: who can do what, under which conditions, up to what limit.",
    body: "A Runtime Policy is one rule, written once and enforced everywhere: which agent (acting on whose behalf), which action, under which conditions (amount limits, categories, timing), gets allowed, denied, or sent to a human for review. Every edit creates a new version rather than overwriting the old one, so you can always see exactly what a rule said at any point in time and who changed it. A rule only takes effect once it's reviewed, compiled, and published -- a draft never silently governs a real action.",
  },
  {
    id: "authority_graph",
    term: "Authority Graph",
    summary: "The map of who can act, on whose behalf, over what, drawn automatically from your real documents.",
    body: "When you upload your governance documents (delegation of authority policies, approval matrices, procurement or HR policy), the AI Authority Builder reads them together and draws out the underlying structure: which roles exist, what they're allowed to do, what limits apply, and where two documents disagree with each other. That structure is the Authority Graph. It's never published automatically -- every finding is a reviewable claim, cited back to the exact document and location it came from, until a person promotes it into an actual Runtime Policy.",
  },
  {
    id: "evidence",
    term: "Evidence",
    summary: "A signed, unchangeable record of exactly what was decided, and why -- proof you can hand to an auditor.",
    body: "Every action Runtime Authority evaluates produces an Evidence record: what was requested, which of your organisation's rules applied, what the outcome was, and a cryptographic signature over the whole thing. That signature means the record can't be altered afterward without it being detectable -- not by this platform, not by anyone. An auditor, insurer, or regulator can verify a piece of Evidence independently, without having to trust this system's own word for it.",
  },
  {
    id: "agent_certificate",
    term: "Agent Certificate",
    summary: "An AI agent's cryptographic ID card: proof it really is who it says it is.",
    body: "Every registered AI agent gets its own certificate, tied to a private key only that agent holds. Every action it submits is signed with that key, so the platform can verify the request genuinely came from that specific agent and hasn't been tampered with in transit. If an agent is compromised or decommissioned, its certificate is rotated or revoked, immediately cutting off its ability to act -- the same way you'd deactivate an employee's access badge.",
  },
  {
    id: "ai_authority_builder",
    term: "AI Authority Builder",
    summary: "Reads your real governance documents and drafts the rules for you, instead of you writing them by hand.",
    body: "Most organisations already have their delegation-of-authority policy written down somewhere -- a PDF, a policy manual, a spreadsheet of approval limits. The AI Authority Builder reads those documents (as many as you have, together, so it can catch contradictions between them) and proposes the Authority Graph and candidate rules for you to review. You never have to translate your existing policy into rule-writing syntax by hand; you review what it found, and promote what's correct.",
  },
  {
    id: "runtime_decision",
    term: "Runtime Decision",
    summary: "The actual outcome when an agent tries to act: allowed, denied, or sent to a human.",
    body: "A Runtime Decision is the record of one specific moment: an agent tried to do something, and Runtime Authority checked it against the authority your organisation already delegated. There are exactly three outcomes: Allow (it matched an active rule cleanly), Deny (a rule explicitly forbids it), or Human Review (nothing clearly matched, so a person decides rather than the system guessing). Every decision, regardless of outcome, produces its own signed Evidence record.",
  },
  {
    id: "assurance",
    term: "Assurance",
    summary: "The at-a-glance view of whether your governance is actually working the way you think it is.",
    body: "Assurance is where you see whether your organisation's delegated authority is actually being evaluated the way you expect: how many actions were within delegated authority, how many were escalated to a human, how many fell outside it, and whether the underlying decision engine itself (the rule checker, the signing system, the database) is healthy. It's built for the person who needs the summary, not the detail underneath it.",
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
    explanation: "A test (or real) decision came back Denied instead of Approved.",
    steps: [
      "Denied means a rule explicitly forbids this action -- it's not an error, it's the platform doing exactly what it's supposed to do.",
      "Check the decision's reason: it names which rule or condition caused the denial, in plain language, not a raw error code.",
      "If you expected this to be allowed, check whether the right rule is actually published and active for this agent's principal -- a rule still in draft never governs a real decision.",
    ],
    path: "/decisions",
  },
  {
    id: "anthropic_key_missing",
    issue: "Anthropic key missing",
    explanation: "The AI Authority Builder or AI Policy Builder is showing illustrative sample output instead of analyzing your real documents.",
    steps: [
      "This means no Anthropic API key is currently configured on this deployment -- the platform tells you this directly via a banner rather than quietly returning fake results as if they were real.",
      "Everything you see in that state is sample data meant to show you what the feature does, not a real analysis of your uploaded document.",
      "This is a deployment configuration matter for whoever manages your hosting environment, not something fixable from within the product itself.",
    ],
  },
];

export interface DeveloperResource {
  id: string;
  label: string;
  description: string;
  href: string;
}

const WEBSITE_URL = "https://www.aisecurewatch.com";

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
    href: `${WEBSITE_URL}/docs/sdk`,
  },
  {
    id: "integration_examples",
    label: "Integration Examples",
    description: "Worked examples of registering an agent and submitting a signed decision end to end.",
    href: `${WEBSITE_URL}/docs/integration-examples`,
  },
  {
    id: "authentication",
    label: "Authentication",
    description: "How requests are authenticated: the Operator Key, per-developer API keys, and agent certificates.",
    href: `${WEBSITE_URL}/docs/authentication`,
  },
  {
    id: "agent_registration",
    label: "Agent Registration",
    description: "The full agent lifecycle: registration, activation, suspension, rotation, and retirement.",
    href: `${WEBSITE_URL}/docs/agent-registration`,
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
    href: `${WEBSITE_URL}/docs`,
  },
  {
    id: "system_status",
    label: "System Status",
    description: "Whether the platform is healthy right now.",
    href: "/organization",
  },
];
