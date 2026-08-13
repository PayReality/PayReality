import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { invitationsApi, usersApi } from "./api";
import { RequirePermission } from "../auth/RequireAuth";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../live/format";
import { ASSIGNABLE_ROLES, ROLE_LABELS } from "../auth/types";
import { Card } from "../components/ui/card";
import type { Invitation, OrgUser } from "./types";

export function UsersPage() {
  const formId = useId();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<OrgUser[] | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("auditor");
  const [temporaryPassword, setTemporaryPassword] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmingDisableId, setConfirmingDisableId] = useState<string | null>(null);

  // Milestone 3 (Enterprise Surface Isolation): the real email-and-accept
  // invite flow "Add a user" above never was -- that path creates the
  // User directly with a temporary password shown once, no separate
  // accept step. This is additive, not a replacement for it.
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("auditor");
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  function load() {
    usersApi.list().then(setUsers).catch((e) => setMessage(describeApiError(e, "Load users")));
    invitationsApi
      .list("pending")
      .then(setInvitations)
      .catch((e) => setMessage(describeApiError(e, "Load invitations")));
  }
  useEffect(load, []);

  async function inviteMember() {
    if (!inviteEmail.trim()) {
      setMessage("An email is required to invite a member.");
      return;
    }
    setInviting(true);
    setMessage(null);
    try {
      const result = await invitationsApi.invite(inviteEmail, inviteRole);
      setInviteToken(result.raw_token);
      setInviteEmail("");
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Invite member"));
    } finally {
      setInviting(false);
    }
  }

  async function revokeInvitation(id: string) {
    try {
      await invitationsApi.revoke(id);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Revoke invitation"));
    }
  }

  async function createUser() {
    if (!email.trim() || !name.trim()) {
      setMessage("Name and email are both required.");
      return;
    }
    setCreating(true);
    setMessage(null);
    try {
      const result = await usersApi.create(email, name, role);
      setTemporaryPassword(result.temporary_password);
      setEmail("");
      setName("");
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Create user"));
    } finally {
      setCreating(false);
    }
  }

  async function changeRole(userId: string, newRole: string) {
    try {
      await usersApi.updateRole(userId, newRole);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Change role"));
    }
  }

  async function toggleStatus(u: OrgUser) {
    const nextStatus = u.status === "active" ? "disabled" : "active";
    try {
      await usersApi.updateStatus(u.id, nextStatus);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Change status"));
    } finally {
      setConfirmingDisableId(null);
    }
  }

  return (
    <RequirePermission permission="users.manage">
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <div className="mb-6">
          <Link to="/organization" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            ← Organisation Settings
          </Link>
          <h1 className="mt-2 mb-2" style={{ color: "var(--pr-text-primary)" }}>Users</h1>
          <p style={{ color: "var(--pr-text-muted)", fontSize: 13, maxWidth: 640 }}>
            Who can do what. Every role maps to a fixed set of permissions -- see RBAC.md for the
            exact matrix.
          </p>
        </div>

        <Card style={{ marginBottom: 24 }}>
          <h2 className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>Add a user</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div>
              <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Name
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
              <label htmlFor={`${formId}-email`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Email
              </label>
              <input
                id={`${formId}-email`}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-role`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Role
              </label>
              <select
                id={`${formId}-role`}
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              >
                {ASSIGNABLE_ROLES.map((r) => (
                  <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            onClick={createUser}
            disabled={creating}
            className="text-sm font-medium px-4 py-2 rounded-lg"
            style={{ backgroundColor: "var(--pr-authority-blue)", color: "white", opacity: creating ? 0.6 : 1 }}
          >
            {creating ? "Adding..." : "Add user"}
          </button>

          {temporaryPassword && (
            <div className="mt-3 p-3 rounded-lg text-xs" style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}>
              Temporary password (shown once, share it with them directly -- there's no email delivery
              yet): <code>{temporaryPassword}</code>
            </div>
          )}
          {message && <p role="alert" className="text-xs mt-2" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}
        </Card>

        <Card style={{ marginBottom: 24 }}>
          <h2 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Invite a member</h2>
          <p className="text-xs mb-4" style={{ color: "var(--pr-text-muted)" }}>
            Sends a one-time acceptance token instead of setting their password directly -- there's no
            email delivery yet, so share the token with them however you normally would.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div>
              <label htmlFor={`${formId}-invite-email`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Email
              </label>
              <input
                id={`${formId}-invite-email`}
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-invite-role`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Role
              </label>
              <select
                id={`${formId}-invite-role`}
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              >
                {ASSIGNABLE_ROLES.map((r) => (
                  <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            onClick={inviteMember}
            disabled={inviting}
            className="text-sm font-medium px-4 py-2 rounded-lg"
            style={{ backgroundColor: "var(--pr-authority-blue)", color: "white", opacity: inviting ? 0.6 : 1 }}
          >
            {inviting ? "Sending..." : "Send invitation"}
          </button>

          {inviteToken && (
            <div className="mt-3 p-3 rounded-lg text-xs" style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}>
              Invitation token (shown once): <code>{inviteToken}</code>
            </div>
          )}

          {invitations && invitations.length > 0 && (
            <div className="mt-5">
              <h3 className="text-xs font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>Pending invitations</h3>
              <ul className="space-y-1.5">
                {invitations.map((inv) => (
                  <li key={inv.id} className="flex items-center justify-between text-xs">
                    <span style={{ color: "var(--pr-text-secondary)" }}>
                      {inv.email} &middot; {ROLE_LABELS[inv.role as keyof typeof ROLE_LABELS] ?? inv.role}
                    </span>
                    <button type="button" onClick={() => revokeInvitation(inv.id)} style={{ color: "var(--pr-critical-red)" }}>
                      Revoke
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card padding={0} style={{ overflow: "hidden" }}>
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--pr-overlay-05)" }}>
                {["Name", "Email", "Role", "Status", "Last Login", ""].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium" style={{ color: "var(--pr-text-muted)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(users ?? []).map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid var(--pr-overlay-03)" }}>
                  <td className="px-4 py-3" style={{ color: "var(--pr-text-primary)" }}>{u.name}</td>
                  <td className="px-4 py-3" style={{ color: "var(--pr-text-secondary)" }}>{u.email}</td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      onChange={(e) => changeRole(u.id, e.target.value)}
                      disabled={u.id === currentUser?.id}
                      className="text-xs px-2 py-1 rounded-md"
                      style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
                    >
                      {ASSIGNABLE_ROLES.map((r) => (
                        <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <span style={{ color: u.status === "active" ? "var(--pr-trust-green)" : "var(--pr-text-disabled)" }}>
                      {u.status === "active" ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--pr-text-muted)" }}>
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}
                  </td>
                  <td className="px-4 py-3">
                    {u.id !== currentUser?.id && (
                      u.status === "active" ? (
                        confirmingDisableId === u.id ? (
                          <span className="flex items-center gap-2">
                            <button type="button" onClick={() => toggleStatus(u)} className="text-xs" style={{ color: "var(--pr-critical-red)" }}>
                              Confirm disable
                            </button>
                            <button type="button" onClick={() => setConfirmingDisableId(null)} className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button type="button" onClick={() => setConfirmingDisableId(u.id)} className="text-xs" style={{ color: "var(--pr-authority-blue)" }}>
                            Disable
                          </button>
                        )
                      ) : (
                        <button type="button" onClick={() => toggleStatus(u)} className="text-xs" style={{ color: "var(--pr-authority-blue)" }}>
                          Re-enable
                        </button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {users?.length === 0 && (
            <p className="text-sm px-4 py-6" style={{ color: "var(--pr-text-muted)" }}>No users yet.</p>
          )}
        </Card>
      </div>
    </RequirePermission>
  );
}
