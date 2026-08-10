# Cost Assumptions

**Status:** final, Milestone 2, but explicitly **not verified against live Azure pricing** — see `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md` risk #5, unchanged since. These are directional estimates to size-check against the ~$5,000 credit, not a quote. **Validate against the Azure Pricing Calculator or `az` before Milestone 3 applies anything.**

## Rough monthly estimate, both environments combined

| Resource | Rough monthly range | Basis |
|---|---|---|
| Container Apps (prod, `min_replicas=1`, 0.5 vCPU/1GiB) | $15–40 | Consumption plan, always-on at this size |
| Container Apps (staging, `min_replicas=0`) | $0–5 | Scale-to-zero; near-idle |
| Postgres Flexible Server ×2 (`B_Standard_B1ms`, 32 GiB) | $25–45 | Cheapest Burstable tier + storage; prod's geo-redundant backup adds a small premium |
| Blob Storage ×2 | $5–10 | Low volume today (Milestone 7 hasn't moved anything into it yet) |
| Key Vault ×2 | $1–5 | Per-operation pricing, low volume |
| Container Registry, Standard ×2 | ~$40 | Standard SKU's flat monthly fee, ×2 environments |
| Log Analytics + App Insights ×2 | $5–20 | Ingestion-based, low volume at pilot scale |
| Private Endpoints (Key Vault + Storage) ×2 environments | ~$30 | Small fixed hourly charge per endpoint |
| VNet, subnets, Private DNS zones | $0 | No charge for these resource types themselves |
| Terraform state storage (bootstrap) | <$1 | Negligible |
| **Rough total** | **~$120–200/month** | Both environments combined |

## Runway against the $5,000 credit

Even doubling the high end of this estimate for margin of error (~$400/month), the credit covers **over 12 months** of both environments running continuously. At the actual estimated range, it covers well over two years. This is not a precise forecast — it is a sanity check that this design is comfortably, not marginally, within budget, which is what "prefer simplicity" (Milestone 2's own instruction) is meant to produce: a design cheap enough that cost is not the constraint shaping any decision in this document.

## What would change this materially

- Real production traffic significantly above pilot scale (would raise Container Apps and Postgres tier needs — both are variables, changed without a module edit).
- A compliance requirement for longer log retention or Premium-tier services (named in `docs/FUTURE_EXPANSION.md`, not built now).
- Horizontal scaling past `max_replicas=3` (gated on the rate-limiter fix first, per `docs/OPERATIONAL_ASSUMPTIONS.md` — not a cost question at all today).
