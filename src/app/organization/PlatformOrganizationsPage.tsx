import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { platformOrganizationsApi } from "./api";
import { describeApiError } from "../live/format";
import { Card } from "../components/ui/card";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { StatusBadge } from "../components/ui/status-badge";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";
import { Building2 } from "lucide-react";
import type { OrganizationLifecycle } from "./types";

// Milestone 3 (Enterprise Surface Isolation): the first UI ever built for
// creating, listing, deactivating, reactivating, or archiving an
// organization -- before this milestone, an Organization could only be
// created by a startup-only server hook, with no API or UI of any kind
// (confirmed in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md). Every call
// here is platform-admin-only: it requires the Operator Key AND an
// explicit organization id on the ones that act on one, set via the
// Operator Key field in the sidebar (OperatorKeyField.tsx) -- there is no
// ordinary per-tenant permission that grants this, by design (Role.OWNER
// governs one organization, not every organization).
export function PlatformOrganizationsPage() {
  const formId = useId();
  const [organizations, setOrganizations] = useState<OrganizationLifecycle[] | null>(null);
  const [name, setName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function load() {
    platformOrganizationsApi
      .list()
      .then(setOrganizations)
      .catch((e) => setMessage(describeApiError(e, "Load organizations")));
  }
  useEffect(load, []);

  async function createOrganization() {
    if (!name.trim() || !ownerEmail.trim() || !ownerName.trim()) {
      setMessage("Name, owner name, and owner email are all required.");
      return;
    }
    setCreating(true);
    setMessage(null);
    try {
      const result = await platformOrganizationsApi.create(name, ownerEmail, ownerName);
      setTemporaryPassword(result.temporary_password);
      setName("");
      setOwnerEmail("");
      setOwnerName("");
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Create organization"));
    } finally {
      setCreating(false);
    }
  }

  async function transition(org: OrganizationLifecycle, action: "deactivate" | "reactivate" | "archive") {
    try {
      if (action === "deactivate") await platformOrganizationsApi.deactivate(org.id);
      else if (action === "reactivate") await platformOrganizationsApi.reactivate(org.id);
      else await platformOrganizationsApi.archive(org.id);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Change organization status"));
    }
  }

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-2">
        <Link to="/organization" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
          ← Organisation Settings
        </Link>
      </div>
      <PageHeader
        title="Platform Organizations"
        description="Create, deactivate, reactivate, or archive any organization on this platform. Requires the Operator Key (sidebar): this is a platform-admin capability, not a setting of any one organization."
      />

      <Card style={{ marginBottom: 24 }}>
        <h2 className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>Create an organization</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          <div>
            <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Organization name
            </label>
            <input
              id={`${formId}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg"
              style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
            />
          </div>
          <div>
            <label htmlFor={`${formId}-owner-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Owner name
            </label>
            <input
              id={`${formId}-owner-name`}
              value={ownerName}
              onChange={(e) => setOwnerName(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg"
              style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
            />
          </div>
          <div>
            <label htmlFor={`${formId}-owner-email`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Owner email
            </label>
            <input
              id={`${formId}-owner-email`}
              type="email"
              value={ownerEmail}
              onChange={(e) => setOwnerEmail(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg"
              style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
            />
          </div>
        </div>
        <button
          type="button"
          onClick={createOrganization}
          disabled={creating}
          className="text-sm font-medium px-4 py-2 rounded-lg"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "white", opacity: creating ? 0.6 : 1 }}
        >
          {creating ? "Creating..." : "Create organization"}
        </button>

        {temporaryPassword && (
          <div className="mt-3 p-3 rounded-lg text-xs" style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}>
            Owner's temporary password (shown once): <code>{temporaryPassword}</code>
          </div>
        )}
        {message && <p role="alert" className="text-xs mt-2" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}
      </Card>

      <Card padding={0} style={{ overflow: "hidden" }}>
        <div className="overflow-x-auto">
          <Table>
            <TableHead>
              <TableRow style={{ borderTop: "none", borderBottom: "1px solid var(--pr-overlay-05)" }}>
                {["Name", "Status", "Created", ""].map((h) => (
                  <TableHeaderCell key={h}>{h}</TableHeaderCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {(organizations ?? []).map((org) => (
                <TableRow key={org.id}>
                  <TableCell style={{ color: "var(--pr-text-primary)" }} truncate={false}>{org.name}</TableCell>
                  <TableCell truncate={false}>
                    <StatusBadge
                      color={
                        org.status === "active"
                          ? "var(--pr-trust-green)"
                          : org.status === "deactivated"
                            ? "var(--pr-warning-amber)"
                            : "var(--pr-text-disabled)"
                      }
                      label={org.status === "active" ? "Active" : org.status === "deactivated" ? "Deactivated" : "Archived"}
                    />
                  </TableCell>
                  <TableCell className="text-xs" style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                    {new Date(org.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell truncate={false}>
                    <span className="flex items-center gap-3 text-xs">
                      {org.status === "active" && (
                        <ConfirmButton
                          variant="ghost"
                          size="sm"
                          confirmLabel="Confirm deactivate"
                          onConfirm={() => transition(org, "deactivate")}
                        >
                          Deactivate
                        </ConfirmButton>
                      )}
                      {org.status === "deactivated" && (
                        <>
                          <ConfirmButton
                            variant="ghost"
                            size="sm"
                            confirmLabel="Confirm reactivate"
                            onConfirm={() => transition(org, "reactivate")}
                          >
                            Reactivate
                          </ConfirmButton>
                          <ConfirmButton
                            variant="tint-danger"
                            size="sm"
                            confirmLabel="Confirm archive"
                            onConfirm={() => transition(org, "archive")}
                          >
                            Archive
                          </ConfirmButton>
                        </>
                      )}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {organizations?.length === 0 && (
          <EmptyState icon={Building2} title="No organizations yet" description="Create the first organization on this platform above." />
        )}
      </Card>
    </div>
  );
}
