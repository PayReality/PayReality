import { PageTitle } from "../components/ui"
import { ScoringWeightsPanel } from "../components/ScoringWeightsPanel"
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
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 18 }}>
              <h2>Scoring weights</h2>
              <p>
                The five dimensions (reach, impact, risk, answerability, decision sensitivity) that combine into a
                question's priority score, and how much each one counts.
              </p>
              <ScoringWeightsPanel />
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
          </>
        )}
      </section>
    </>
  )
}
