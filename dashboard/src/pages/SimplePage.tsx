import { PageTitle } from "../components/ui"
import { useAuth } from "../auth/AuthContext"
import { ROLE_LABELS } from "../auth/types"
import type { Page } from "../types"

export function SimplePage({ page }: { page: Page }) {
  const { user } = useAuth()
  return (
    <>
      <PageTitle
        title={page}
        description={
          page === "Settings"
            ? "Your account and organisation details."
            : "How PayReality moves from case evidence to prioritised questions and tested decision logic."
        }
      />
      <section className="panel simple-settings">
        {page === "Settings" ? (
          <>
            <div>
              <h2>Account</h2>
              <p>Read-only account details for your current session.</p>
            </div>
            <div className="status-grid" style={{ marginBottom: 18 }}>
              <div>
                <span>Name</span>
                <strong>{user?.name}</strong>
              </div>
              <div>
                <span>Email</span>
                <strong>{user?.email}</strong>
              </div>
              <div>
                <span>Role</span>
                <strong>{user ? ROLE_LABELS[user.role] ?? user.role : "—"}</strong>
              </div>
              <div>
                <span>Last sign-in</span>
                <strong>{user?.last_login_at ? new Date(user.last_login_at).toLocaleString() : "This session"}</strong>
              </div>
            </div>
            <div className="not-available">
              There are no Decision Intelligence settings to configure yet -- scoring weights and workspace preferences
              are presently fixed in the backend, not admin-configurable. This page will gain real controls once that
              changes, rather than presenting inputs that don't actually save anything.
            </div>
          </>
        ) : (
          <>
            <div>
              <h2>Product guide</h2>
              <p>
                PayReality is intended to discover the smallest, highest-value set of questions that can resolve
                recurring uncertainty across many business decisions.
              </p>
            </div>
            <div className="guide-steps">
              {[
                "Analyse cases and context",
                "Map recurring uncertainty into patterns",
                "Discover and rank priority questions",
                "Obtain an authoritative, separately-approved answer",
                "Construct explicit, versioned decision logic",
                "Replay that logic against real historical cases",
              ].map((s, i) => (
                <div key={s}>
                  <span>{i + 1}</span>
                  <strong>{s}</strong>
                </div>
              ))}
            </div>
            <div className="not-available" style={{ marginTop: 16 }}>
              Not implemented yet, by design: CSV case import, AI-assisted pattern/question suggestion, and any
              report/export beyond the per-workflow overview on the Reports page.
            </div>
          </>
        )}
      </section>
    </>
  )
}
