import { useState } from "react"
import { Button, ErrorNote, PageTitle } from "../components/ui"
import { usersApi } from "../users/api"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"
import { ROLE_LABELS } from "../auth/types"

export function People() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission("users.manage")
  const { data: users, loading, error, reload } = useFetch(() => (canManage ? usersApi.list() : Promise.resolve(null)), [canManage])
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("reviewer")
  const [createError, setCreateError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [newCredential, setNewCredential] = useState<{ email: string; password: string } | null>(null)

  async function handleCreate() {
    if (!name.trim() || !email.trim()) return
    setSubmitting(true)
    setCreateError(null)
    try {
      const result = await usersApi.create({ name: name.trim(), email: email.trim(), role })
      setNewCredential({ email: result.user.email, password: result.temporary_password })
      setCreating(false)
      setName("")
      setEmail("")
      reload()
    } catch (err) {
      setCreateError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!canManage) {
    return (
      <>
        <PageTitle title="People & Ownership" description="Identify who has the authority to answer each question." />
        <div className="permission-note">
          Viewing and managing the organisation's member list requires the Owner role (
          <code>users.manage</code>). Your current role doesn't hold this permission, so this page can't load real member
          data. This is the real backend's own access rule, not a missing feature.
        </div>
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="People & Ownership"
        description="Identify who has the authority to answer each question, not simply who is available."
        actions={
          <Button kind="primary" onClick={() => setCreating(!creating)}>
            {creating ? "Cancel" : "Add team member"}
          </Button>
        }
      />
      {error && <ErrorNote message={error} />}
      {creating && (
        <section className="panel" style={{ marginBottom: 16 }}>
          <div className="form-body">
            <div className="form-grid">
              <label>
                Name *
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label>
                Email *
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
            </div>
            <label>
              Role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {Object.entries(ROLE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {createError && <ErrorNote message={createError} />}
            <Button kind="primary" onClick={handleCreate} disabled={submitting}>
              {submitting ? "Creating…" : "Create user"}
            </Button>
          </div>
        </section>
      )}
      {newCredential && (
        <div className="success" style={{ marginBottom: 16 }}>
          <span>
            <strong>Account created for {newCredential.email}</strong>
            One-time temporary password: <code>{newCredential.password}</code>. This is shown exactly once; there is no
            email delivery in this platform yet, so share it with them directly.
          </span>
        </div>
      )}
      <div className="people-grid">
        {(users ?? []).map((p) => (
          <div className="person-card" key={p.id} style={{ cursor: "default" }}>
            <div className="avatar large">{p.name.slice(0, 2).toUpperCase()}</div>
            <div>
              <h3>{p.name}</h3>
              <p>{ROLE_LABELS[p.role] ?? p.role}</p>
              <span>{p.email}</span>
            </div>
            <div className="person-stats">
              <strong>{p.status}</strong>
              <span>{p.last_login_at ? `Active ${new Date(p.last_login_at).toLocaleDateString()}` : "Never signed in"}</span>
            </div>
          </div>
        ))}
        {!loading && (users ?? []).length === 0 && (
          <div style={{ color: "var(--muted)", fontSize: 12 }}>No other team members yet.</div>
        )}
      </div>
    </>
  )
}
