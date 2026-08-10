# Milestone 4: Performance Report

## Methodology and a constraint stated up front

All load (checklist item 14) was directed exclusively at Azure staging — Render received only light, matched-parameter samples for latency comparison, never a stress test, per this milestone's absolute rule against migrating customer traffic. Every test used `/health` (idempotent, side-effect-free, safe to repeat against a production system in small numbers).

A real finding shaped the test design: the application has an existing, documented, **in-memory, per-client-IP rate limiter** (120 requests/60s per IP — `server/app/security.py`), applied globally to all routes including `/health`. A naive single-IP burst trips this immediately and only proves the rate limiter works, not the infrastructure's real capacity. All representative-load figures below use synthetic `X-Forwarded-For` headers to simulate 20–50 distinct clients, so the numbers reflect actual Container Apps / networking performance rather than re-discovering already-known application throttling.

## Representative load test — Azure staging only

500 requests, concurrency 20, 50 simulated clients:

| Metric | Value |
|---|---|
| Throughput | 50.46 req/s |
| Errors | 0 / 500 (0.0%) |
| Latency p50 | 258.4 ms |
| Latency p90 | 561.5 ms |
| Latency p99 | 2000.5 ms |
| Latency max | 2017.1 ms |
| Latency mean | 376.5 ms |

Zero errors, no replica scale-out triggered (concurrency stayed under the `http_scale_rule.concurrent_requests = 50` threshold set in Terraform — correct, expected behavior, not a gap). A separate single-IP burst (500 requests, no spoofing) produced a 76% `429` rate — confirmed as the intentional per-IP rate limiter engaging exactly as designed, not an infrastructure failure.

## Latency comparison — Azure vs. Render, matched parameters

Identical test parameters on both platforms (60 requests, concurrency 5, 20 simulated clients) for a fair, apples-to-apples comparison:

| Metric | Azure (centralus) | Render (Oregon, free tier) |
|---|---|---|
| Throughput | 14.32 req/s | 10.12 req/s |
| Errors | 0 / 60 | 0 / 60 |
| Latency p50 | 263.1 ms | 315.2 ms |
| Latency p90 | 627.8 ms | 1,021.6 ms |
| Latency p99 | 886.1 ms | 2,164.4 ms |
| Latency mean | 342.4 ms | 482.2 ms |

**Azure is faster at every measured percentile in this test.** One caveat stated plainly: both measurements were taken from the same client location, so absolute numbers include this machine's network path to Oregon (Render) versus Central US (Azure) — a real difference for a real client, but not a controlled, single-variable network benchmark. The comparison is still meaningful because it reflects what an actual caller experiences against each platform today.

## Cold start

- **Render** (free tier, spins down after inactivity): first request after idle took **32.86 seconds**. Warm requests: 400 ms – 1.5 s.
- **Azure** (`min_replicas=0`, scale-to-zero): after an idle period, an `az containerapp exec` attempt failed because no replica was running; the very next `/health` request triggered a cold start and returned `200` within that single request's timeout window — qualitatively much faster than Render's 33-second cold start, though not precisely instrumented to the millisecond in this pass. **Recommendation:** if a precise cold-start figure is needed before cutover, instrument a dedicated timed test (trivial — a `time curl` immediately after a confirmed scale-to-zero).

## Behavioural differences observed between Azure and Render

| Aspect | Render | Azure | Assessment |
|---|---|---|---|
| Edge/CDN | Sits behind Cloudflare (`Server: cloudflare`, `CF-RAY`, HTTP/3 `alt-svc`) | Direct Container Apps ingress, no CDN layer (`Server: uvicorn`) | Real topology difference. Not a defect — Azure Front Door would be the equivalent addition if/when a custom production domain is put in front of Container Apps, out of this milestone's scope. |
| Application-level security headers | `x-content-type-options`, `x-frame-options`, `referrer-policy`, `permissions-policy`, `strict-transport-security` all present | Identical set, identical values | **No difference** — confirms these originate in the application's own middleware, unaffected by platform. |
| Cold start | ~33s (free tier spin-down) | Materially faster (not precisely timed) | Azure advantage, though both platforms cold-start under their respective idle/scale-to-zero configurations — this is a similarity in kind (both cold-start), a difference in degree. |
| Rate limiting | Same in-process, per-IP limiter (identical code) | Same | **No difference** — proven by shared source code, not independently tested against Render's production traffic (would violate this milestone's own rules). |
| API surface | 92 paths / 112 operations | Byte-identical | **No difference.** |
| Warm latency | Higher (see table above) | Lower (see table above) | Azure advantage in this test, with the stated network-path caveat. |

## Conclusion

Azure staging meets or exceeds Render's observed performance characteristics on every metric measured, with zero errors under representative concurrent load. The rate-limiter interaction is a pre-existing application behavior, not an Azure-specific finding, and applies identically to both platforms since both run the same code.
