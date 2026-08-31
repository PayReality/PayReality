# Demo Narrative Source

**This is a source document only. It does not rebuild the demo.** The next demo milestone should build from this narrative rather than rediscovering the story; this milestone deliberately stops short of touching `src/app/demo/`.

## The canonical scenario

An AI procurement agent, operating inside a real enterprise's accounts-payable workflow, attempts to change a supplier's bank details — the classic vendor-fraud-risk action, and one every finance/security audience immediately recognizes as high-stakes.

### Beat 1 — the attempt, corroborated

1. The AI agent attempts `ChangeSupplierBankDetails` against the enterprise's ERP.
2. The organization's **Trusted Adapter** — running inside the enterprise's own environment, not PayReality's — observes the real operation and reports it to PayReality using its approved **Action Mapping**: *"ChangeSupplierBankDetails means Update supplier bank details."*
3. On screen: name the three questions explicitly as they resolve — *who's acting* (the agent), *what's attesting* (the Trusted Adapter, via the approved mapping), *is it authorized* (PayReality, next).

### Beat 2 — the decision

4. PayReality checks the Trusted Connection is active, the Agent is on this Runtime Connection's explicit allow-list, and the mapping matches — then evaluates the organization's actual Runtime Policy.
5. Show either outcome, both real and both worth demonstrating:
   - **HUMAN_REVIEW**: this specific action (changing payment routing) is exactly the kind of thing this organization's policy routes to a human, every time, by design — not a failure, a feature.
   - **DENY**: the request falls outside anything the organization has actually authorized.
6. Show the **Evidence** and **Authorization Receipt** for the decision: agent, Trusted Adapter, external operation, external operation ID, the exact Action Mapping version, environment, the policy version that applied, and the cryptographic verification status. Say plainly: this proves the decision was made and by what authority — it does not claim the bank-detail change itself was blocked or executed; that's a separate, honestly-disclosed boundary (§ below).

### Beat 3 — the retry, proven idempotent

7. The same external operation is reported again — a network retry, exactly as a real ERP would do on a timeout.
8. PayReality returns the **same** Decision, not a new evaluation. This is the concrete, provable payoff of operation idempotency: the enterprise system's own retry behavior can never manufacture a second, possibly-different authority decision for the same real event.

### Beat 4 — the ALLOW example

9. A second, lower-stakes action — e.g. an ordinary invoice payment already within the organization's approved, delegated limit — goes through the identical mechanism and resolves `ALLOW`, with its own signed Evidence and Receipt.
10. This is the necessary counterweight to Beat 2: the story isn't "PayReality blocks things," it's "PayReality makes a real, provable, deterministic decision every time — sometimes yes, sometimes no, sometimes 'ask a human,' never a guess."

## What this narrative must never claim

Everything in [WEBSITE_CLAIMS.md](WEBSITE_CLAIMS.md)'s prohibited list applies here without exception. Specifically for this demo: never say or imply that PayReality itself stopped the bank-detail change from executing, that the Trusted Adapter proves the change never happened, or that a Capability Authorization was issued for this Adapter-mediated flow (none is, by deliberate design — see [TRUSTED_ADAPTER_GUIDE.md](TRUSTED_ADAPTER_GUIDE.md)). The honest, and still strong, claim is: *a real, deterministic, provable authority decision was made and evidenced, corroborated by a second, independent, customer-controlled party* — not *PayReality physically stopped the money from moving*.

## Tone for a nontechnical enterprise viewer

Lead with the three-question framing (who's acting / what's attesting / is it authorized) every single time integration comes up — it's the one piece of vocabulary that makes the rest of the story make sense to someone who has never heard "Adapter" or "Action Mapping" before. Avoid backend nouns entirely in narration (no "EnforcementBinding," no "IntegrationIdentity") — see [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.3 for the customer-facing-term mapping.
