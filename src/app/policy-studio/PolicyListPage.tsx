import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { policyStudioApi } from "./api";
import type { RuntimePolicy } from "./types";
import { PolicyStatusBadge } from "./components/PolicyStatusBadge";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import { HelpIcon } from "../help/HelpIcon";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";

type SortKey = "name" | "version" | "status" | "created_at" | "owner";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "version", label: "Version" },
  { key: "status", label: "Status" },
  { key: "created_at", label: "Last Modified" },
  { key: "owner", label: "Owner" },
];

// Each key's natural starting direction, matching what the "Sort by"
// dropdown always did before headers became clickable (name/status/owner
// A-Z, version/created_at highest-or-newest first) -- so picking a column
// from either control lands on the same order.
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  name: "asc",
  version: "desc",
  status: "asc",
  created_at: "desc",
  owner: "asc",
};

export function PolicyListPage() {
  const [policies, setPolicies] = useState<RuntimePolicy[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>(DEFAULT_DIR.created_at);

  function load() {
    setError(null);
    policyStudioApi
      .list()
      .then(setPolicies)
      .catch((e) => setError(describeApiError(e, "Loading policies")));
  }

  useEffect(load, []);
  // Milestone 13 Phase 6A: catches a policy deployed/activated/retired
  // from another tab, or this tab having been left open and revisited.
  useResourceSync(["policies"], load);

  function selectSort(key: SortKey) {
    setSortKey(key);
    setSortDir(DEFAULT_DIR[key]);
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      selectSort(key);
    }
  }

  const visible = useMemo(() => {
    if (!policies) return [];
    let rows = policies;
    if (statusFilter !== "all") rows = rows.filter((p) => p.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((p) => p.name.toLowerCase().includes(q));
    }
    const sorted = [...rows].sort((a, b) => {
      if (sortKey === "name") return a.name.localeCompare(b.name);
      if (sortKey === "version") return a.version - b.version;
      if (sortKey === "status") return a.status.localeCompare(b.status);
      if (sortKey === "owner") return (a.metadata.owner ?? "").localeCompare(b.metadata.owner ?? "");
      return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    });
    return sortDir === "asc" ? sorted : sorted.reverse();
  }, [policies, search, statusFilter, sortKey, sortDir]);

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <h1 style={{ color: "var(--pr-text-primary)" }}>Governance</h1>
          <HelpIcon articleId="runtime_policy" />
        </div>
        <div className="flex items-center gap-3">
          <Link to="/governance/dashboard" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            Dashboard
          </Link>
          <Link to="/governance/approvals" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            Approvals
          </Link>
          <Link
            to="/governance/new"
            className="px-4 py-2 rounded-lg text-sm font-medium border"
            style={{ borderColor: "var(--pr-authority-blue)", color: "var(--pr-authority-blue)" }}
          >
            + Write a rule
          </Link>
          <Link
            to="/governance/authority-builder"
            className="px-4 py-2 rounded-lg text-sm font-medium"
            style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
          >
            Discover from documents
          </Link>
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          aria-label="Search policies by name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name"
          style={{
            backgroundColor: "var(--pr-bg-hover)",
            border: "1px solid var(--pr-overlay-10)",
            color: "var(--pr-text-primary)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
            width: 260,
          }}
        />
        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            backgroundColor: "var(--pr-bg-hover)",
            border: "1px solid var(--pr-overlay-10)",
            color: "var(--pr-text-primary)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
          }}
        >
          <option value="all">All statuses</option>
          <option value="draft">Draft</option>
          <option value="pending_review">Pending review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="compiled">Compiled</option>
          <option value="active">Active</option>
          <option value="retired">Retired</option>
          <option value="archived">Archived</option>
        </select>
        <select
          aria-label="Sort by"
          value={sortKey}
          onChange={(e) => selectSort(e.target.value as SortKey)}
          style={{
            backgroundColor: "var(--pr-bg-hover)",
            border: "1px solid var(--pr-overlay-10)",
            color: "var(--pr-text-primary)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
          }}
        >
          <option value="created_at">Last modified</option>
          <option value="name">Name</option>
          <option value="version">Version</option>
          <option value="status">Status</option>
          <option value="owner">Owner</option>
        </select>
      </div>

      {error && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{error}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!policies && !error && (
        <div className="space-y-3">
          <Skeleton height={32} />
          <Skeleton height={32} />
          <Skeleton height={32} />
          <Skeleton height={32} />
        </div>
      )}

      {policies && (
        <table className="w-full text-sm" style={{ color: "var(--pr-text-primary)" }}>
          <thead>
            <tr style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12 }}>
              {COLUMNS.map((col) => (
                <th key={col.key} className="pb-2">
                  <button
                    onClick={() => toggleSort(col.key)}
                    className="flex items-center gap-1"
                    style={{ color: "inherit", fontSize: 12, fontWeight: sortKey === col.key ? 600 : 400 }}
                    aria-label={`Sort by ${col.label}`}
                  >
                    {col.label}
                    {sortKey === col.key && <span aria-hidden="true">{sortDir === "asc" ? "↑" : "↓"}</span>}
                  </button>
                </th>
              ))}
              <th className="pb-2" title="Whether this policy enforces a resolved Authority Builder Authority, or free-text delegation only">Authority</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <tr
                key={p.policy_key}
                className="transition-colors"
                style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              >
                <td className="py-2">
                  <Link to={`/governance/${p.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>
                    {p.name}
                  </Link>
                </td>
                <td className="py-2">v{p.version}</td>
                <td className="py-2">
                  <PolicyStatusBadge status={p.status} />
                </td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>
                  {new Date(p.created_at).toLocaleDateString()}
                </td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>
                  {p.metadata.owner ?? "N/A"}
                </td>
                <td className="py-2" title={p.constraints.authority_id ? "Enforces a resolved Authority" : "Free-text delegation only"}>
                  {p.constraints.authority_id ? (
                    <span aria-label="Linked to a resolved Authority" style={{ color: "var(--pr-authority-blue)" }}>&#9679;</span>
                  ) : (
                    <span aria-label="No resolved Authority" style={{ color: "var(--pr-text-muted)" }}>&#9675;</span>
                  )}
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center" style={{ color: "var(--pr-text-muted)" }}>
                  {policies.length === 0 ? "No policies yet." : "No policies match your filters."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
