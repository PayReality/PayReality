# Sprint 1, Part 5 — Observability Foundation

**Status:** final. **Principle:** one lightweight tool covering error tracking and basic performance monitoring, plus the health-check/log infrastructure that already exists — not a Prometheus + Grafana + Jaeger + PagerDuty stack. At today's traffic volume that stack would be more infrastructure to operate than the thing it's observing.

## What already exists (keep, unchanged)

- Structured JSON request logs (`request_id`, `method`, `path`, `status`, `duration_ms`).
- `/health` (liveness), `/health/ready` (live-checked DB + OPA reachability, timeout-bounded), `/version` (build identity).
- A synthetic end-to-end smoke test (`scripts/smoke_test.py`) covering the real submission → evaluation → evidence pipeline.

## What this sprint adds

### Logging
No new logging framework. **Addition:** ensure every unhandled exception is captured with full context (request_id, stack trace) by whatever error tracker is added below — today an unhandled exception produces a log line but nothing that aggregates or deduplicates recurring errors across requests.

### Metrics — what should be monitored

| Metric | Why it matters here specifically |
|---|---|
| Request rate, latency (p50/p95/p99), error rate — per endpoint | Standard baseline; the only way to know "normal" before something is "abnormal." |
| **Decision outcome counts over time** (`ALLOW`/`DENY`/`HUMAN_REVIEW`) | Domain-specific: a sudden absence of `ALLOW` (everything failing closed) or a spike in `DENY` is a signal something upstream broke — a bad policy deploy, an OPA problem, a Runtime Truth resolution failure — long before a customer would think to report it. |
| **`HUMAN_REVIEW` backlog size** (decisions pending resolution, age of oldest pending one) | Domain-specific: this platform's own fail-closed design means backlog growth is the direct, measurable cost of any upstream problem. Nothing today tracks this at all. |
| OPA query latency, as observed by the Decision Engine's own `timeout_ms` budget | Directly tied to a real, already-fail-closed code path (`OPATimeoutError` in `domain/decision/engine.py`) — trending toward that timeout is an early warning before it starts actually firing. |
| Database connection/query latency | Standard, and this app has exactly one database, so this is cheap to add and high-signal. |

### Tracing
**Not adding distributed tracing (OpenTelemetry/Jaeger) this sprint.** The current topology is one process; OPA runs embedded in the same container, not a network hop. Full distributed tracing has no genuine target to trace across yet — the request-scoped `request_id` already threaded through the structured logs gives the same "follow one request through the system" capability this topology actually needs. Revisit if/when OPA or another dependency moves to a genuinely separate network service.

### Error tracking / basic APM
**Add Sentry (or an equivalent single lightweight product)** at the FastAPI middleware/service layer — never inside `domain/decision/engine.py`, which must stay free of any import beyond `dataclasses`/`typing` (Phase 2's own tested boundary; adding instrumentation there would break a test that already exists, not just a principle). Sentry's free/low tiers cover both error aggregation and basic transaction performance monitoring in one integration, which is why a separate metrics stack isn't needed to get the two highest-value observability capabilities this sprint identifies as missing.

### Alerting — classified by what it means operationally

**Page immediately (P1):**
- `/health/ready` failing for more than a short, defined grace window (e.g. 2 consecutive scheduled checks).
- The API process crash-looping (repeated restarts within a short window).
- 5xx error rate crossing a fixed threshold over a rolling window.
- The scheduled smoke test failing.
- TLS certificate within a fixed number of days of expiry (both Render and Vercel auto-renew, but "auto-renew silently failed" is exactly the kind of thing that should page rather than be discovered when a customer's browser shows a warning).

**Notify, business hours (P2):**
- `HUMAN_REVIEW` backlog exceeding a fixed size or age threshold.
- p95 latency elevated but not yet timing out.
- Database storage or connection-count approaching a defined limit.
- The free-tier-database-expiry class of risk generally: any resource with a known, dated limit should notify well before the deadline, not on the day of.

**Informational only, no alert:**
- Individual `DENY` decisions (this is the system working correctly, not a failure).
- Routine deploys.
- Any single slow request below the P2 threshold.
- Normal AI-feature `configuration_required` states (`ANTHROPIC_API_KEY` absent is a valid, intentional state, not a fault).

### Health checks
No new endpoints needed — `/health`, `/health/ready`, and `/version` already exist and already check the right things. What's missing is **consumption**, not the checks themselves: nothing outside this codebase currently polls them on a schedule (this is the same gap the prior sprint's roadmap named as Q-C2b; this sprint's [08_ENGINEERING_IMPLEMENTATION_PLAN.md](08_ENGINEERING_IMPLEMENTATION_PLAN.md) is where it actually gets built rather than re-scoped).
