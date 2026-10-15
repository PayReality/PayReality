import { Icon } from "./ui"
import type { Page } from "../types"
import { useAuth } from "../auth/AuthContext"
import { ROLE_LABELS } from "../auth/types"

const nav: { label: Page; icon: string }[] = [
  { label: "Overview", icon: "grid" },
  { label: "Workflows", icon: "flow" },
  { label: "Cases", icon: "file" },
  { label: "Patterns", icon: "pattern" },
  { label: "Discovery", icon: "search" },
  { label: "Questions", icon: "question" },
  { label: "Decision Logic", icon: "branch" },
  { label: "Testing & Replay", icon: "play" },
  { label: "Reports", icon: "report" },
]

const secondaryNav: { label: Page; icon: string }[] = [
  { label: "People & Ownership", icon: "users" },
  { label: "Settings", icon: "settings" },
  { label: "Help & Documentation", icon: "help" },
]

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function Sidebar({
  page,
  setPage,
  collapsed,
  setCollapsed,
  questionsAwaitingAnswer,
}: {
  page: Page
  setPage: (p: Page) => void
  collapsed: boolean
  setCollapsed: (v: boolean) => void
  questionsAwaitingAnswer: number | null
}) {
  const { user } = useAuth()
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <img src="/payreality-logo.png" alt="" className="brand-mark" />
        {!collapsed && <span>PayReality</span>}
        <button
          className="collapse"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed(!collapsed)}
        >
          <Icon name="chevron" />
        </button>
      </div>
      <div className="workspace-card">
        {!collapsed && (
          <>
            <span>Workspace</span>
            <strong>Decision Intelligence</strong>
          </>
        )}
        <div className="workspace-dot" />
      </div>
      <nav>
        <div className="nav-section">{!collapsed && <span>Analyse</span>}</div>
        {nav.map((item) => (
          <button
            key={item.label}
            title={item.label}
            className={`nav-item ${page === item.label ? "active" : ""}`}
            onClick={() => setPage(item.label)}
          >
            <Icon name={item.icon} />
            {!collapsed && <span>{item.label}</span>}
            {!collapsed && item.label === "Questions" && !!questionsAwaitingAnswer && (
              <em>{questionsAwaitingAnswer}</em>
            )}
          </button>
        ))}
        <div className="nav-spacer" />
        <div className="nav-section">{!collapsed && <span>Workspace</span>}</div>
        {secondaryNav.map((item) => (
          <button
            key={item.label}
            title={item.label}
            className={`nav-item ${page === item.label ? "active" : ""}`}
            onClick={() => setPage(item.label)}
          >
            <Icon name={item.icon} />
            {!collapsed && <span>{item.label}</span>}
          </button>
        ))}
      </nav>
      <button className="user-card" onClick={() => setPage("Settings")} title="Open profile settings">
        <div className="avatar">{user ? initialsFor(user.name) : "?"}</div>
        {!collapsed && user && (
          <div>
            <strong>{user.name}</strong>
            <span>{ROLE_LABELS[user.role] ?? user.role}</span>
          </div>
        )}
      </button>
    </aside>
  )
}
