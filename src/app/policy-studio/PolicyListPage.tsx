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
import { Select } from "../components/ui/select";
import { Skeleton } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";
import { ShieldCheck } from "lucide-react";

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
      <PageHeader
        title="Governance"
        description="Where your organization's authority is established: the rules that decide what an agent may do, and on whose delegated authority."
        status={<HelpIcon articleId="runtime_policy" />}
      />
      <div className="flex items-center flex-wrap gap-3 mb-4">
        <Link to="/governance/dashboard" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
          Dashboard
        </Link>
        <Link to="/governance/approvals" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
          Approvals
        </Link>
        <Link
          to="/governance/new"
          className="px-4 py-2 rounded-lg text-sm font-medium border sm:ml-auto flex-shrink-0"
          style={{ borderColor: "var(--pr-authority-blue)", color: "var(--pr-authority-blue)" }}
        >
          + Write a rule
        </Link>
        <Link
          to="/governance/authority-builder"
          className="px-4 py-2 rounded-lg text-sm font-medium flex-shrink-0"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
        >
          Discover from documents
        </Link>
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
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
        <Select
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
        </Select>
        <Select
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
        </Select>
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
        <div className="overflow-x-auto">
        <Table>
          <TableHead>
            <TableRow style={{ borderTop: "none" }}>
              {COLUMNS.map((col) => (
                <TableHeaderCell key={col.key}>
                  <button
                    onClick={() => toggleSort(col.key)}
                    className="flex items-center gap-1 uppercase tracking-wide"
                    style={{ color: "inherit", fontWeight: sortKey === col.key ? 600 : 400 }}
                    aria-label={`Sort by ${col.label}`}
                  >
                    {col.label}
                    {sortKey === col.key && <span aria-hidden="true">{sortDir === "asc" ? "↑" : "↓"}</span>}
                  </button>
                </TableHeaderCell>
              ))}
              <TableHeaderCell title="Whether this policy enforces a resolved Authority Builder Authority, or free-text delegation only">Authority source</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((p) => (
              <TableRow
                key={p.policy_key}
                className="transition-colors"
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              >
                <TableCell truncate={false}>
                  <Link to={`/governance/${p.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>
                    {p.name}
                  </Link>
                </TableCell>
                <TableCell truncate={false}>v{p.version}</TableCell>
                <TableCell truncate={false}>
                  <PolicyStatusBadge status={p.status} />
                </TableCell>
                <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                  {new Date(p.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                  {p.metadata.owner ?? "N/A"}
                </TableCell>
                <TableCell style={{ fontSize: 12 }} title={p.constraints.authority_id ? "This policy enforces a resolved Authority Builder Authority" : "This policy's delegated_by is free text, not linked to a resolved Authority"} truncate={false}>
                  {p.constraints.authority_id ? (
                    <span style={{ color: "var(--pr-authority-blue)" }}>Linked authority</span>
                  ) : (
                    <span style={{ color: "var(--pr-text-muted)" }}>Free-text only</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} truncate={false}>
                  <EmptyState
                    icon={ShieldCheck}
                    title={policies.length === 0 ? "No policies yet" : "No policies match your filters"}
                    description={
                      policies.length === 0
                        ? "Write a rule, or discover authority from your organization's own documents."
                        : "Try a different search or status."
                    }
                  />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        </div>
      )}
    </div>
  );
}
