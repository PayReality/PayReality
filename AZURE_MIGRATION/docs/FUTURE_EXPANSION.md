# Future Expansion Notes

**Status:** final, Milestone 2. Every item here is named because this milestone's own work surfaced a real, understood reason it might someday be needed — none is built now, and none should be built until its own trigger condition is actually met.

| Expansion | Trigger condition | Where it would land |
|---|---|---|
| Container Apps workload profiles (dedicated compute) | `max_replicas=3` on the consumption plan is genuinely reached and sustained | `modules/container-apps`; the `container-apps` subnet is already sized `/23` specifically so this doesn't require re-addressing |
| Zone-redundant HA for Postgres | A real incident is caused by a zone-level infrastructure failure (none has been, so far) | `modules/postgres`, `var.high_availability_enabled` already exists, defaulted off |
| NAT Gateway for static outbound IP | A third-party integration requires IP allowlisting | `modules/networking` |
| Container Registry Premium (geo-replication, registry-level Private Endpoint) | A second region, or a compliance requirement naming registry-level network isolation specifically | `modules/container-registry` |
| Azure Front Door / Application Gateway (WAF) | A specific WAF or multi-region-routing requirement, not yet identified by any risk analysis in this program | New module, not yet named |
| Moving the rate limiter to a shared store (Redis) | Before `max_replicas` is ever raised above 3 | Application code change, tracked as Sprint 1's own deferred Task T12, not a Terraform change |
| Longer log retention | A compliance requirement (SOC 2 or similar, explicitly out of this program's scope) names a specific window | `modules/monitoring`, `var.log_retention_days` |
| Custom domain / DNS binding | Milestone 9's cutover, not a future-expansion item at all — already scheduled, just not yet reached | `modules/container-apps` ingress, plus DNS provider (not Azure DNS — see `docs/KNOWN_RISKS.md`) |
| GitHub Actions deployment workflow | Milestone 6 | `.github/workflows/`, using the CI/CD identity this milestone already federates |
