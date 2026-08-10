# Milestone 3: Cost Report

## Method

The subscription is hours old — `az consumption usage list` returns zero rows, since Azure's billing pipeline lags actual resource creation by roughly a day. There is no real invoice to reconcile against yet. Instead, this report validates Milestone 2's `docs/COST_ASSUMPTIONS.md` estimate against **live Azure Retail Prices API data** for the exact SKUs and region actually deployed (`centralus`), which is the honest substitute available at this stage.

## Confirmed retail prices (centralus, live query)

| SKU | Meter | Retail price | Monthly (×730 hrs, single instance) |
|---|---|---|---|
| PostgreSQL Flexible Server `B1MS` (Burstable) | vCore-hour | $0.01921/hr | ~$14.02 |
| Container Registry, Standard | Registry-day | $0.6666/day | ~$20.00 |

## Comparison against Milestone 2's estimate

| Line item | Milestone 2 estimate (both environments) | Live-priced reality | Assessment |
|---|---|---|---|
| Postgres Flexible Server ×2 (`B1ms`, 32 GiB) | $25–45/mo | ~$14.02 × 2 = $28.04/mo compute, plus ~32 GiB storage at Azure's standard $0.10/GiB-mo ≈ $6.40 total → **~$34.44/mo** | Within estimated range |
| Container Registry, Standard ×2 | ~$40/mo | $20.00 × 2 = **$40.00/mo exactly** | Matches estimate precisely |
| Container Apps (staging, `min_replicas=0`) | $0–5/mo | Not independently re-priced this milestone; staging is currently `min_replicas=0` (scale-to-zero), consistent with the low end of the original estimate | Consistent |
| Everything else (Key Vault, Storage, Log Analytics/App Insights, Private Endpoints, VNet/DNS) | $6–65/mo combined | Not independently re-priced this milestone (all low-volume, ingestion- or per-operation-priced meters; no reason from this milestone's findings to expect a material deviation) | No evidence of deviation |

**Nothing found this milestone is materially higher than Milestone 2 expected.** The two line items actually re-priced against live data both land inside or exactly at the original estimate.

## New cost the estimate didn't anticipate

None from Azure resources. Two Key Vaults now exist against this subscription's naming (`kv-pr-staging-adzg`, soft-deleted, and `kv-pr-staging-lu2swm`, active) for the 90-day retention window ending 2026-11-08 — a soft-deleted vault is not billed for compute, but it does still count toward the subscription's overall resource footprint. Not expected to be a cost driver.

## Runway against the $5,000 credit

Unchanged from Milestone 2's conclusion: even at double the original high-end estimate, the credit covers well over a year of both environments running continuously. Nothing discovered this milestone changes that conclusion.
