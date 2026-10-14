import { useState, type ReactNode } from "react"

// Shared presentational components, lifted verbatim (visual language
// unchanged, per the task brief) from the original single-file
// prototype App.tsx into their own module so real pages can import them.

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    flow: (
      <>
        <rect x="3" y="4" width="7" height="6" rx="1" />
        <rect x="14" y="14" width="7" height="6" rx="1" />
        <path d="M10 7h3a4 4 0 0 1 4 4v3M14 17h-3a4 4 0 0 1-4-4v-3" />
      </>
    ),
    file: (
      <>
        <path d="M6 2h8l4 4v16H6z" />
        <path d="M14 2v5h5M9 12h6M9 16h6" />
      </>
    ),
    pattern: (
      <>
        <circle cx="6" cy="7" r="3" />
        <circle cx="18" cy="7" r="3" />
        <circle cx="12" cy="18" r="3" />
        <path d="m8 9 3 6m5-6-3 6" />
      </>
    ),
    question: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.7 9a2.5 2.5 0 1 1 3.3 2.4c-.7.3-1 .8-1 1.6M12 17h.01" />
      </>
    ),
    branch: (
      <>
        <circle cx="6" cy="5" r="2" />
        <circle cx="18" cy="6" r="2" />
        <circle cx="18" cy="18" r="2" />
        <path d="M8 5h3a4 4 0 0 1 4 4v7M8 5v9a4 4 0 0 0 4 4h4" />
      </>
    ),
    play: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m10 8 6 4-6 4z" />
      </>
    ),
    report: (
      <>
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </>
    ),
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M16 3a4 4 0 0 1 0 8m6 10v-2a4 4 0 0 0-3-3.87" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.6-1H3v-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6V3h4v.09A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.6 1h.09v4H21a1.7 1.7 0 0 0-1.6 1z" />
      </>
    ),
    help: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.7 9a2.5 2.5 0 1 1 3.3 2.4c-.7.3-1 .8-1 1.6M12 17h.01" />
      </>
    ),
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    bell: (
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
      </>
    ),
    chevron: <path d="m9 18 6-6-6-6" />,
    down: <path d="m6 9 6 6 6-6" />,
    more: (
      <>
        <circle cx="5" cy="12" r="1" fill="currentColor" />
        <circle cx="12" cy="12" r="1" fill="currentColor" />
        <circle cx="19" cy="12" r="1" fill="currentColor" />
      </>
    ),
    close: (
      <>
        <path d="M6 6l12 12M18 6 6 18" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    filter: <path d="M3 5h18l-7 8v6l-4 2v-8z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    download: (
      <>
        <path d="M12 3v12m-5-5 5 5 5-5M5 21h14" />
      </>
    ),
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    lock: (
      <>
        <rect x="4" y="11" width="16" height="9" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 8 0v4" />
      </>
    ),
  }
  return (
    <svg
      aria-hidden="true"
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name] || paths.help}
    </svg>
  )
}

export function Button({
  children,
  kind = "secondary",
  icon,
  onClick,
  disabled = false,
  title,
  type = "button",
}: {
  children?: ReactNode
  kind?: "primary" | "secondary" | "ghost" | "danger"
  icon?: string
  onClick?: () => void
  disabled?: boolean
  title?: string
  type?: "button" | "submit"
}) {
  return (
    <button className={`btn ${kind}`} onClick={onClick} disabled={disabled} title={title} type={type}>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  )
}

export function Select({
  value,
  onChange,
  children,
  label,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  children: ReactNode
  label: string
  disabled?: boolean
}) {
  return (
    <label className="select-wrap">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {children}
      </select>
      <Icon name="down" size={14} />
    </label>
  )
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function PageTitle({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string
  description: string
  actions?: ReactNode
  eyebrow?: string
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">{eyebrow ?? "Decision Intelligence"}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="title-actions">{actions}</div>}
    </div>
  )
}

export function TableToolbar({
  search,
  setSearch,
  resultsLabel,
}: {
  search: string
  setSearch: (v: string) => void
  resultsLabel?: string
}) {
  return (
    <div className="table-toolbar">
      <label className="input-search">
        <Icon name="search" size={16} />
        <input
          aria-label="Search records"
          placeholder="Search records…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <Button kind="ghost" onClick={() => setSearch("")}>
        Clear
      </Button>
      {resultsLabel && <span className="results-count">{resultsLabel}</span>}
    </div>
  )
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="callout" style={{ borderLeftColor: "var(--red)", background: "var(--red-soft)", color: "var(--red)" }}>
      <strong>Something went wrong</strong>
      <span>{message}</span>
    </div>
  )
}

export function LoadingPanel({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="panel" style={{ padding: 32, textAlign: "center", color: "var(--muted)", fontSize: 12 }}>
      {label}
    </div>
  )
}

export function EmptyPanel({ title, body }: { title: string; body: string }) {
  return (
    <div className="panel" style={{ padding: 32, textAlign: "center" }}>
      <strong style={{ display: "block", marginBottom: 6, fontSize: 13 }}>{title}</strong>
      <span style={{ color: "var(--text-2)", fontSize: 12 }}>{body}</span>
    </div>
  )
}

export function useToggle(initial = false): [boolean, () => void] {
  const [v, setV] = useState(initial)
  return [v, () => setV((x) => !x)]
}
