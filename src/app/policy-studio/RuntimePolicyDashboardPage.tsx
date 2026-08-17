import { useEffect, useState } from "react";
import { Link } from "react-router";
import { policyLifecycleApi } from "./lifecycleApi";
import { PolicyStatusBadge } from "./components/PolicyStatusBadge";
import { formatStatus, describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { SkeletonRows } from "../components/ui/skeleton";
import type { LifecycleDashboard, PolicyLifecycleSummary, PolicySearchParams } from "./types";

function PolicyRow({ p, note }: { p: PolicyLifecycleSummary; note?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
      <div className="flex items-center gap-3">
        <Link to={`/governance/${p.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>{p.name}</Link>
        <span style={{ color: "var(--pr-text-muted)" }}>v{p.version}</span>
        <PolicyStatusBadge status={p.effective_status} />
      </div>
      {note && <span style={{ color: "var(--pr-text-muted)" }}>{note}</span>}
    </div>
  );
}

// Runtime Policy Dashboard + Search (Phase 5, RUNTIME_POLICY_LIFECYCLE.md
// sections 9-10), folded into one page rather than two destinations --
// the same "related views, one page" pattern already used for Versions+
// Diff and Compile+DryRun+Deploy elsewhere in Policy Studio.
export function RuntimePolicyDashboardPage() {
  const [dashboard, setDashboard] = useState<LifecycleDashboard | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  const [filters, setFilters] = useState<PolicySearchParams>({});
  const [results, setResults] = useState<PolicyLifecycleSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  function loadDashboard() {
    setDashboardError(null);
    policyLifecycleApi.dashboard().then(setDashboard).catch((e) => setDashboardError(describeApiError(e, "Loading the dashboard")));
  }

  useEffect(loadDashboard, []);
  // Milestone 13 Phase 6A: catches a policy lifecycle transition made
  // from another tab, or this tab having been left open and revisited.
  useResourceSync(["policies"], loadDashboard);

  async function runSearch() {
    setSearching(true);
    setSearchError(null);
    try {
      const r = await policyLifecycleApi.search(filters);
      setResults(r.results);
    } catch (e) {
      setSearchError(describeApiError(e, "Search"));
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setFilters({});
    setResults(null);
  }

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-6 flex items-center justify-between">
        <h1 style={{ color: "var(--pr-text-primary)" }}>Runtime Policy Dashboard</h1>
        <Link to="/governance" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>Back to list</Link>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Search</h2>
        <div className="flex flex-wrap gap-2 mb-3">
          {(["principal", "resource", "action", "reviewer"] as const).map((key) => (
            <input
              key={key}
              aria-label={`Search by ${key}`}
              placeholder={formatStatus(key)}
              value={filters[key] ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value || undefined }))}
              style={{
                backgroundColor: "var(--pr-bg-hover)", border: "1px solid var(--pr-overlay-10)",
                color: "var(--pr-text-primary)", borderRadius: 6, padding: "6px 10px", fontSize: 13, width: 160,
              }}
            />
          ))}
          <select
            aria-label="Search by state"
            value={filters.state ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, state: e.target.value || undefined }))}
            style={{
              backgroundColor: "var(--pr-bg-hover)", border: "1px solid var(--pr-overlay-10)",
              color: "var(--pr-text-primary)", borderRadius: 6, padding: "6px 10px", fontSize: 13,
            }}
          >
            <option value="">Any state</option>
            {["draft", "pending_review", "approved", "rejected", "compiled", "active", "retired", "superseded", "archived"].map((s) => (
              <option key={s} value={s}>{formatStatus(s)}</option>
            ))}
          </select>
          <input
            aria-label="Search by version"
            type="number"
            placeholder="Version"
            value={filters.version ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, version: e.target.value ? Number(e.target.value) : undefined }))}
            style={{
              backgroundColor: "var(--pr-bg-hover)", border: "1px solid var(--pr-overlay-10)",
              color: "var(--pr-text-primary)", borderRadius: 6, padding: "6px 10px", fontSize: 13, width: 90,
            }}
          />
          <Button onClick={runSearch} disabled={searching}>{searching ? "Searching..." : "Search"}</Button>
          {results && <Button variant="ghost" onClick={clearSearch}>Clear</Button>}
        </div>
        {searchError && <Alert severity="error">{searchError}</Alert>}
        {results && (
          <div>
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginBottom: 4 }}>{results.length} result(s)</p>
            {results.map((p) => <PolicyRow key={`${p.policy_key}-${p.version}`} p={p} />)}
            {results.length === 0 && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No matches.</p>}
          </div>
        )}
      </Card>

      {dashboardError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{dashboardError}</span>
            <Button variant="ghost" size="sm" onClick={loadDashboard}>Retry</Button>
          </div>
        </Alert>
      )}

      {!dashboard && !dashboardError && <SkeletonRows count={4} height={24} />}

      {dashboard && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Policies by state</h2>
            <div className="flex flex-wrap gap-4">
              {Object.entries(dashboard.counts_by_state).map(([state, count]) => (
                <div key={state} style={{ fontSize: 13 }}>
                  <PolicyStatusBadge status={state as PolicyLifecycleSummary["effective_status"]} /> {count}
                </div>
              ))}
            </div>
          </Card>

          {dashboard.conflict_alerts.length > 0 && (
            <Card style={{ marginBottom: 16, borderColor: "var(--pr-critical-red)" }}>
              <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-critical-red)" }}>
                Conflict alerts ({dashboard.conflict_alerts.length})
              </h2>
              {dashboard.conflict_alerts.map((a) => (
                <p key={`${a.policy_key}-${a.version}`} style={{ fontSize: 13, marginBottom: 4 }}>
                  <Link to={`/governance/${a.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>Policy v{a.version}</Link>
                  {" "}has {a.violations.length} safety issue(s): {a.violations.map((v) => v.check).join(", ")}
                </p>
              ))}
            </Card>
          )}

          <Card style={{ marginBottom: 16 }}>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>
              Pending approvals ({dashboard.pending_approvals.length})
            </h2>
            {dashboard.pending_approvals.map((p) => <PolicyRow key={p.policy_key} p={p} />)}
            {dashboard.pending_approvals.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Nothing waiting on review.</p>
            )}
          </Card>

          <Card style={{ marginBottom: 16 }}>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Upcoming changes</h2>
            {dashboard.upcoming_activations.map((s) => (
              <div key={s.id} className="flex justify-between py-1" style={{ fontSize: 13, borderTop: "1px solid var(--pr-overlay-05)" }}>
                <Link to={`/governance/${s.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>Activate v{s.version}</Link>
                <span style={{ color: "var(--pr-text-muted)" }}>{new Date(s.effective_at).toLocaleString()}</span>
              </div>
            ))}
            {dashboard.upcoming_retirements.map((s) => (
              <div key={s.id} className="flex justify-between py-1" style={{ fontSize: 13, borderTop: "1px solid var(--pr-overlay-05)" }}>
                <Link to={`/governance/${s.policy_key}`} style={{ color: "var(--pr-warning-amber)" }}>Retire v{s.version}</Link>
                <span style={{ color: "var(--pr-text-muted)" }}>{new Date(s.effective_at).toLocaleString()}</span>
              </div>
            ))}
            {dashboard.upcoming_expirations.map((p) => (
              <PolicyRow key={p.policy_key} p={p} note={p.effective_until ? `expires ${new Date(p.effective_until).toLocaleDateString()}` : undefined} />
            ))}
            {dashboard.upcoming_activations.length === 0 &&
              dashboard.upcoming_retirements.length === 0 &&
              dashboard.upcoming_expirations.length === 0 && (
                <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Nothing scheduled.</p>
              )}
          </Card>

          <Card style={{ marginBottom: 16 }}>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Recently activated</h2>
            {dashboard.recently_activated.map((p) => (
              <PolicyRow key={p.policy_key} p={p} note={p.activated_by ? `by ${p.activated_by}` : undefined} />
            ))}
            {dashboard.recently_activated.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Nothing activated yet.</p>
            )}
          </Card>

          <Card style={{ marginBottom: 16 }}>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Deprecated policies</h2>
            {dashboard.deprecated_policies.map((p) => (
              <PolicyRow key={p.policy_key} p={p} note={p.deprecation_reason ?? undefined} />
            ))}
            {dashboard.deprecated_policies.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>None.</p>
            )}
          </Card>

          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Rollback history</h2>
            {dashboard.rollback_history.map((p) => (
              <PolicyRow key={`${p.policy_key}-${p.version}`} p={p} note={`rolled back to v${p.rollback_of_version}`} />
            ))}
            {dashboard.rollback_history.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No rollbacks recorded.</p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
