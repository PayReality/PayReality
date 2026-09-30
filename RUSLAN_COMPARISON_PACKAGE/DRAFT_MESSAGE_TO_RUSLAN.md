Draft only -- not sent. For review before any contact.

---

Subject: EvidenceBound / PayReality recovery-scenario comparison (EVIDENCEBOUND-PAYREALITY-RECOVERY-V01)

Hi Ruslan,

Following up on the recovery-scenario interop work under
`EVIDENCEBOUND-PAYREALITY-RECOVERY-V01` -- I've put together a package comparing what PayReality's
runtime actually does, verified against real code this session, for the schedules we'd discussed:
late-reported commitment after revocation, an unresolved outcome after revocation, and two
distinct concurrency scenarios (capability consumption, and first-attempt registration at a new
business-operation identity).

Everything in the package is real output from real tests against real application code (SQLite and
Postgres, never mocked) -- I've tried to be explicit throughout about which facts came from
PayReality's own code versus which came from the test harness's synthetic destination standing in
for a real external system, so nothing here should read as a claim about a real destination system
we haven't actually integrated against.

A few things worth flagging directly, since I'd rather you hear them from me than find them
yourselves:

- PayReality does not independently verify a destination outcome. Every "commit" fact traces back
  to either a signature-verified Adapter's own report, or an explicit human override -- there's no
  channel of our own to the destination system itself.
- Automatic duplicate-attempt protection is opt-in per submission (a caller has to declare a
  `business_operation_id`), not universal across every code path.
- During this same review I found and fixed a real bug: an ordinary, transient issuance rejection
  (e.g. an Agent suspended between authorization and issuance) could previously leave a business
  operation permanently blocked for all future legitimate attempts. It's fixed and covered by a
  regression test now, but I want to be upfront that it existed until this pass.

The package includes a README, the five sanitized trace files, a contract-vs-observed matrix, and
exact reproduction commands, in case you'd like to rerun any of it yourselves.

Would it make sense to do the same in reverse -- a comparable trace set from EvidenceBound's own
side for these same schedules -- so we're comparing two real systems' actual behavior rather than
two sets of claims?

Best,
[name]
