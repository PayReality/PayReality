import { useMemo, useState } from "react"

type Page = "Overview" | "Workflows" | "Cases" | "Patterns" | "Questions" | "Decision Logic" | "Testing & Replay" | "Reports" | "People & Ownership" | "Settings" | "Help & Documentation"

type Modal = "search" | "export" | "new-question" | "assign" | "replay" | "notifications" | null

const nav: { label: Page; icon: string; badge?: string }[] = [
  { label: "Overview", icon: "grid" },
  { label: "Workflows", icon: "flow" },
  { label: "Cases", icon: "file" },
  { label: "Patterns", icon: "pattern" },
  { label: "Questions", icon: "question", badge: "4" },
  { label: "Decision Logic", icon: "branch" },
  { label: "Testing & Replay", icon: "play" },
  { label: "Reports", icon: "report" },
]

const secondaryNav: { label: Page; icon: string }[] = [
  { label: "People & Ownership", icon: "users" },
  { label: "Settings", icon: "settings" },
  { label: "Help & Documentation", icon: "help" },
]

const questions = [
  {
    rank: 1,
    question:
      "Who is authorised to approve a settlement when multiple policyholders are involved?",
    pattern: "Settlement authority is unclear",
    cases: 42,
    impact: "High",
    risk: "High",
    evidence: "72%",
    owner: "Maya Chen",
    status: "Awaiting approval",
  },
  {
    rank: 2,
    question:
      "Which evidence is required before shared ownership can be confirmed?",
    pattern: "Required evidence is repeatedly absent",
    cases: 31,
    impact: "High",
    risk: "Medium",
    evidence: "61%",
    owner: "Unassigned",
    status: "Awaiting owner",
  },
  {
    rank: 3,
    question:
      "When should a conflicting beneficiary record trigger specialist review?",
    pattern: "Records produce conflicting interpretations",
    cases: 24,
    impact: "Medium",
    risk: "High",
    evidence: "84%",
    owner: "Ravi Patel",
    status: "Ready for testing",
  },
  {
    rank: 4,
    question:
      "Which exceptions require judgement rather than a standard decision path?",
    pattern: "Human judgement boundary is unclear",
    cases: 18,
    impact: "Medium",
    risk: "Medium",
    evidence: "48%",
    owner: "Elena Ortiz",
    status: "Needs evidence",
  },
]

const cases = [
  [
    "CLM-10482",
    "Settlement approval",
    "Escalated",
    "Authority unclear",
    "Needs review",
  ],
  [
    "CLM-10471",
    "Evidence assessment",
    "Human review",
    "Missing information",
    "In review",
  ],
  [
    "CLM-10439",
    "Settlement approval",
    "Resolved",
    "Authority unclear",
    "Reviewed",
  ],
  [
    "CLM-10398",
    "Beneficiary validation",
    "Escalated",
    "Conflicting rules",
    "Needs review",
  ],
  [
    "CLM-10377",
    "Exception routing",
    "Human review",
    "Human judgement",
    "In review",
  ],
]

const patterns = [
  {
    name: "Settlement authority is unclear",
    description:
      "Cases with multiple policyholders do not share an explicit authority path.",
    cases: 42,
    share: "17.0%",
    state: "Observed pattern",
    strength: "Strong evidence",
  },
  {
    name: "Required evidence is repeatedly absent",
    description:
      "Shared ownership evidence is unavailable at the point of decision.",
    cases: 31,
    share: "12.6%",
    state: "Observed pattern",
    strength: "Moderate evidence",
  },
  {
    name: "Policy interpretations conflict",
    description:
      "Two policy excerpts lead reviewers toward different decision paths.",
    cases: 24,
    share: "9.7%",
    state: "Candidate pattern",
    strength: "Moderate evidence",
  },
  {
    name: "Human judgement boundary is unclear",
    description:
      "Exceptions lack an agreed threshold for specialist intervention.",
    cases: 18,
    share: "7.3%",
    state: "Candidate pattern",
    strength: "Early evidence",
  },
]

function Icon({ name, size = 18 }: { name: string; size?: number }) {
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

function Button({
  children,
  kind = "secondary",
  icon,
  onClick,
  disabled = false,
}: {
  children?: React.ReactNode
  kind?: "primary" | "secondary" | "ghost" | "danger"
  icon?: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button className={`btn ${kind}`} onClick={onClick} disabled={disabled}>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  )
}

function Select({
  value,
  onChange,
  children,
  label,
}: {
  value: string
  onChange: (v: string) => void
  children: React.ReactNode
  label: string
}) {
  return (
    <label className="select-wrap">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <Icon name="down" size={14} />
    </label>
  )
}

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode
  tone?: string
}) {
  return <span className={`badge ${tone}`}>{children}</span>
}

function PageTitle({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: React.ReactNode
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">Illustrative prototype data</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="title-actions">{actions}</div>}
    </div>
  )
}

function Sidebar({
  page,
  setPage,
  collapsed,
  setCollapsed,
}: {
  page: Page
  setPage: (p: Page) => void
  collapsed: boolean
  setCollapsed: (v: boolean) => void
}) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <div className="brand-mark">P</div>
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
            <strong>Northstar Labs</strong>
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
            {!collapsed && item.badge && <em>{item.badge}</em>}
          </button>
        ))}
        <div className="nav-spacer" />
        <div className="nav-section">
          {!collapsed && <span>Workspace</span>}
        </div>
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
      <button
        className="user-card"
        onClick={() => setPage("Settings")}
        title="Open profile settings"
      >
        <div className="avatar">AO</div>
        {!collapsed && (
          <div>
            <strong>Alex Owen</strong>
            <span>Product administrator</span>
          </div>
        )}
      </button>
    </aside>
  )
}

function Topbar({
  page,
  setModal,
  workflow,
  setWorkflow,
}: {
  page: Page
  setModal: (m: Modal) => void
  workflow: string
  setWorkflow: (v: string) => void
}) {
  const [profile, setProfile] = useState(false)
  return (
    <header className="topbar">
      <div className="crumbs">
        <span>Northstar Labs</span>
        <Icon name="chevron" size={13} />
        <strong>{page}</strong>
      </div>
      <div className="top-actions">
        <Select
          label="Selected workflow"
          value={workflow}
          onChange={setWorkflow}
        >
          <option>Claims Assessment</option>
          <option>Invoice Exception Review</option>
          <option>Customer Refund Decisions</option>
        </Select>
        <button className="search-trigger" onClick={() => setModal("search")}>
          <Icon name="search" size={16} />
          <span>Search anything…</span>
          <kbd>⌘ K</kbd>
        </button>
        <button
          className="icon-btn notification"
          title="Open notifications"
          onClick={() => setModal("notifications")}
        >
          <Icon name="bell" />
          <i />
        </button>
        <div className="profile-wrap">
          <button
            className="avatar top-avatar"
            title="Open profile menu"
            onClick={() => setProfile(!profile)}
          >
            AO
          </button>
          {profile && (
            <div className="menu">
              <button onClick={() => setProfile(false)}>View profile</button>
              <button onClick={() => setProfile(false)}>Preferences</button>
              <button onClick={() => setProfile(false)}>
                Sign out of prototype
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

function Overview({
  setPage,
  setModal,
  period,
  setPeriod,
}: {
  setPage: (p: Page) => void
  setModal: (m: Modal) => void
  period: string
  setPeriod: (p: string) => void
}) {
  const [selectedPattern, setSelectedPattern] = useState(0)
  const metrics = [
    ["Cases analysed", "247", "Case set with traceable sources", "Cases"],
    [
      "Recurring uncertainty",
      "115",
      "Across four observed or candidate patterns",
      "Patterns",
    ],
    [
      "Priority questions",
      "12",
      "Ranked by inspectable candidate factors",
      "Questions",
    ],
    ["Awaiting an answer", "4", "Require an authoritative owner", "Questions"],
  ] as const
  return (
    <>
      <PageTitle
        title="Overview"
        description="Understand where your AI workflow encounters uncertainty, which questions matter most, and what should be tested next."
        actions={
          <>
            <Button icon="download" onClick={() => setModal("export")}>
              Export report
            </Button>
            <Button kind="primary" onClick={() => setPage("Questions")}>
              Review priority questions
            </Button>
          </>
        }
      />
      <div className="control-strip">
        <div>
          <span className="control-label">Analysis scope</span>
          <strong>Claims Assessment</strong>
        </div>
        <Select label="Analysis period" value={period} onChange={setPeriod}>
          <option>Last 90 days</option>
          <option>Last 30 days</option>
          <option>2026 pilot period</option>
        </Select>
        <div className="date-control">01 Jul — 30 Sep 2026</div>
        <Badge tone="info">Designed capability</Badge>
      </div>
      <div className="kpi-grid">
        {metrics.map(([label, value, caption, destination], i) => (
          <button
            className="kpi"
            key={label}
            onClick={() => setPage(destination)}
          >
            <div className="kpi-top">
              <span>{label}</span>
              <span className="kpi-icon">0{i + 1}</span>
            </div>
            <strong>{value}</strong>
            <p>{caption}</p>
            <div className="kpi-link">
              Explore <Icon name="arrow" size={14} />
            </div>
          </button>
        ))}
      </div>
      <div className="overview-grid">
        <section className="panel uncertainty-panel">
          <div className="panel-heading">
            <div>
              <h2>Recurring uncertainty</h2>
              <p>What repeatedly prevents a confident decision</p>
            </div>
            <Button kind="ghost" onClick={() => setPage("Patterns")}>
              View patterns
            </Button>
          </div>
          <div className="chart-labels">
            <span>Pattern category</span>
            <span>Affected cases</span>
          </div>
          {patterns.map((pattern, i) => (
            <button
              className={`bar-row ${selectedPattern === i ? "selected" : ""}`}
              key={pattern.name}
              onMouseEnter={() => setSelectedPattern(i)}
              onClick={() => setPage("Patterns")}
            >
              <div className="bar-copy">
                <strong>{pattern.name}</strong>
                <span>{pattern.description}</span>
              </div>
              <div className="bar-track">
                <i style={{ width: `${100 - i * 16}%` }} />
              </div>
              <div className="bar-value">
                <strong>{pattern.cases}</strong>
                <span>{pattern.share}</span>
              </div>
            </button>
          ))}
          <div className="chart-note">
            <Icon name="help" size={15} />
            <span>
              Categories are analytical hypotheses. Review evidence before
              treating a candidate pattern as established.
            </span>
          </div>
        </section>
        <section className="panel priority-panel">
          <div className="panel-heading">
            <div>
              <h2>Priority questions</h2>
              <p>Questions with the greatest potential decision leverage</p>
            </div>
            <Badge tone="info">Illustrative rank</Badge>
          </div>
          {questions.slice(0, 3).map((q) => (
            <button
              className="question-card"
              key={q.rank}
              onClick={() => setPage("Questions")}
            >
              <div className="rank">{q.rank}</div>
              <div className="question-main">
                <strong>{q.question}</strong>
                <span>{q.pattern}</span>
                <div className="question-meta">
                  <span>
                    <b>{q.cases}</b> cases potentially affected
                  </span>
                  <Badge tone={q.risk === "High" ? "warning" : "neutral"}>
                    {q.risk} risk
                  </Badge>
                </div>
              </div>
              <Icon name="chevron" size={16} />
            </button>
          ))}
          <Button kind="ghost" onClick={() => setPage("Questions")}>
            View all priority questions <Icon name="arrow" size={14} />
          </Button>
        </section>
      </div>
      <div className="lower-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Recommended next actions</h2>
              <p>Ordered by dependency, not automated advice</p>
            </div>
          </div>
          {[
            [
              "Review proposed authority answer",
              "Policy owner input unlocks versioned logic.",
              "Questions",
            ],
            [
              "Resolve conflicting evidence",
              "Two policy excerpts support different paths.",
              "Cases",
            ],
            [
              "Configure a historical replay",
              "Evaluate approved logic before any deployment.",
              "Testing & Replay",
            ],
          ].map(([title, text, to], i) => (
            <button
              className="action-row"
              key={title}
              onClick={() => setPage(to as Page)}
            >
              <span>{i + 1}</span>
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
              <Icon name="chevron" size={16} />
            </button>
          ))}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Recent activity</h2>
              <p>Recorded within this prototype workspace</p>
            </div>
          </div>
          {[
            [
              "Pattern identified",
              "Settlement authority is unclear",
              "18 min",
              "Patterns",
            ],
            ["Evidence added", "Case CLM-10482", "2 hr", "Cases"],
            [
              "Answer submitted",
              "Authority under shared ownership",
              "Yesterday",
              "Questions",
            ],
            [
              "Simulated replay completed",
              "Authority logic · v0.3",
              "2 days",
              "Testing & Replay",
            ],
          ].map(([kind, item, time, to]) => (
            <button
              className="activity-row"
              key={item}
              onClick={() => setPage(to as Page)}
            >
              <div className="activity-dot" />
              <div>
                <span>{kind}</span>
                <strong>{item}</strong>
              </div>
              <time>{time}</time>
            </button>
          ))}
        </section>
      </div>
    </>
  )
}

function TableToolbar({
  search,
  setSearch,
  onFilter,
}: {
  search: string
  setSearch: (v: string) => void
  onFilter: () => void
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
      <Button icon="filter" onClick={onFilter}>
        Filters
      </Button>
      <Button kind="ghost" onClick={() => setSearch("")}>
        Clear
      </Button>
      <span className="results-count">Illustrative records</span>
    </div>
  )
}

function Cases({ openCase }: { openCase: (id: string) => void }) {
  const [search, setSearch] = useState("")
  const [filtered, setFiltered] = useState(false)
  const [pageNumber, setPageNumber] = useState(1)
  const visible = cases
    .filter((row) => row.join(" ").toLowerCase().includes(search.toLowerCase()))
    .filter((row) => !filtered || row[2] === "Escalated")
  return (
    <>
      <PageTitle
        title="Cases"
        description="Inspect the source evidence behind recurring uncertainty without treating any single case as the complete explanation."
        actions={
          <Button onClick={() => setFiltered(!filtered)} icon="filter">
            {filtered ? "Clear escalation filter" : "Show escalated"}
          </Button>
        }
      />
      <div className="scope-banner">
        <Icon name="file" />
        <div>
          <strong>Evidence foundation</strong>
          <span>
            Case content is fictional and excludes personal or confidential
            information. Sources, analysis and human conclusions are shown
            separately.
          </span>
        </div>
      </div>
      <section className="panel table-panel">
        <TableToolbar
          search={search}
          setSearch={setSearch}
          onFilter={() => setFiltered(!filtered)}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Case reference</th>
                <th>Decision type</th>
                <th>Disposition</th>
                <th>Uncertainty</th>
                <th>Review status</th>
                <th>Case date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row, i) => (
                <tr key={row[0]} onClick={() => openCase(row[0])}>
                  <td>
                    <strong>{row[0]}</strong>
                  </td>
                  <td>{row[1]}</td>
                  <td>
                    <Badge
                      tone={row[2] === "Escalated" ? "warning" : "neutral"}
                    >
                      {row[2]}
                    </Badge>
                  </td>
                  <td>{row[3]}</td>
                  <td>{row[4]}</td>
                  <td>Sep {18 - i}, 2026</td>
                  <td>
                    <button
                      className="row-open"
                      title={`Open ${row[0]}`}
                      onClick={() => openCase(row[0])}
                    >
                      <Icon name="chevron" size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <span>
            Page {pageNumber} · Showing {visible.length} of 247 cases
          </span>
          <div>
            <Button
              disabled={pageNumber === 1}
              onClick={() => setPageNumber(Math.max(1, pageNumber - 1))}
            >
              Previous
            </Button>
            <Button
              kind={pageNumber === 1 ? "primary" : "secondary"}
              onClick={() => setPageNumber(1)}
            >
              1
            </Button>
            <Button
              kind={pageNumber === 2 ? "primary" : "secondary"}
              onClick={() => setPageNumber(2)}
            >
              2
            </Button>
            <Button onClick={() => setPageNumber(Math.min(25, pageNumber + 1))}>
              Next
            </Button>
          </div>
        </div>
      </section>
    </>
  )
}

function Patterns({ setPage }: { setPage: (p: Page) => void }) {
  const [search, setSearch] = useState("")
  const [reviewed, setReviewed] = useState<string[]>([])
  return (
    <>
      <PageTitle
        title="Recurring patterns"
        description="See what emerges across cases: repeated uncertainty, its evidence, and the questions that could resolve it."
        actions={
          <Button kind="primary" onClick={() => setPage("Questions")}>
            Explore candidate questions
          </Button>
        }
      />
      <section className="panel table-panel">
        <TableToolbar
          search={search}
          setSearch={setSearch}
          onFilter={() => setSearch("authority")}
        />
        <div className="pattern-list">
          {patterns
            .filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
            .map((p, i) => (
              <article className="pattern-item" key={p.name}>
                <div className="pattern-index">0{i + 1}</div>
                <div className="pattern-copy">
                  <div className="pattern-title">
                    <h3>{p.name}</h3>
                    <Badge
                      tone={
                        p.state.includes("Candidate") ? "warning" : "success"
                      }
                    >
                      {p.state}
                    </Badge>
                  </div>
                  <p>{p.description}</p>
                  <div className="pattern-facts">
                    <span>
                      <strong>{p.cases}</strong> related cases
                    </span>
                    <span>
                      <strong>{p.share}</strong> of case set
                    </span>
                    <span>{p.strength}</span>
                  </div>
                </div>
                <div className="pattern-actions">
                  <Button onClick={() => setPage("Cases")}>View cases</Button>
                  <Button kind="ghost" onClick={() => setPage("Questions")}>
                    Related questions
                  </Button>
                  <Button
                    kind="ghost"
                    onClick={() => setReviewed([...reviewed, p.name])}
                  >
                    {reviewed.includes(p.name)
                      ? "Marked for review"
                      : "Mark for review"}
                  </Button>
                </div>
              </article>
            ))}
        </div>
      </section>
    </>
  )
}

function Questions({
  setModal,
  setPage,
}: {
  setModal: (m: Modal) => void
  setPage: (p: Page) => void
}) {
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<number[]>([])
  const [detail, setDetail] = useState(1)
  const [tab, setTab] = useState("Rationale")
  const [approved, setApproved] = useState(false)
  const q = questions.find((item) => item.rank === detail)!
  return (
    <>
      <PageTitle
        title="Priority Questions"
        description="Discover which unanswered questions could resolve the most recurring uncertainty across your AI workflow."
        actions={
          <>
            <Button onClick={() => setModal("export")}>Export selected</Button>
            <Button
              kind="primary"
              icon="plus"
              onClick={() => setModal("new-question")}
            >
              New question
            </Button>
          </>
        }
      />
      <div className="explain-strip">
        <div>
          <strong>How ranking works</strong>
          <span>
            Candidate factors: reach, decision impact, risk, answerability,
            evidence, reuse and validation feasibility.
          </span>
        </div>
        <Button kind="ghost" onClick={() => setTab("Rationale")}>
          Inspect assumptions
        </Button>
      </div>
      <section className="panel table-panel">
        <TableToolbar
          search={search}
          setSearch={setSearch}
          onFilter={() => setSearch("author")}
        />
        {selected.length > 0 && (
          <div className="bulk-bar">
            <strong>{selected.length} selected</strong>
            <Button onClick={() => setModal("assign")}>Assign owner</Button>
            <Button onClick={() => setSelected([])}>Clear selection</Button>
          </div>
        )}
        <div className="table-scroll">
          <table className="question-table">
            <thead>
              <tr>
                <th></th>
                <th>Rank</th>
                <th>Question</th>
                <th>Reach</th>
                <th>Impact</th>
                <th>Risk</th>
                <th>Evidence</th>
                <th>Owner</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {questions
                .filter((x) =>
                  x.question.toLowerCase().includes(search.toLowerCase()),
                )
                .map((item) => (
                  <tr
                    key={item.rank}
                    className={detail === item.rank ? "active-row" : ""}
                    onClick={() => setDetail(item.rank)}
                  >
                    <td>
                      <input
                        aria-label={`Select question ${item.rank}`}
                        type="checkbox"
                        checked={selected.includes(item.rank)}
                        onChange={() =>
                          setSelected(
                            selected.includes(item.rank)
                              ? selected.filter((x) => x !== item.rank)
                              : [...selected, item.rank],
                          )
                        }
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td>
                      <span className="rank-small">{item.rank}</span>
                    </td>
                    <td>
                      <strong>{item.question}</strong>
                      <span className="cell-sub">{item.pattern}</span>
                    </td>
                    <td>{item.cases} cases</td>
                    <td>{item.impact}</td>
                    <td>
                      <Badge
                        tone={item.risk === "High" ? "warning" : "neutral"}
                      >
                        {item.risk}
                      </Badge>
                    </td>
                    <td>{item.evidence}</td>
                    <td>{item.owner}</td>
                    <td>
                      <Badge tone="info">{item.status}</Badge>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel detail-panel">
        <div className="detail-head">
          <div>
            <div className="eyebrow">
              Question Q-{String(q.rank).padStart(3, "0")} · Proposed by
              cross-case analysis
            </div>
            <h2>{q.question}</h2>
            <div className="inline-meta">
              <Badge tone={approved ? "success" : "warning"}>
                {approved ? "Approved in prototype" : q.status}
              </Badge>
              <span>Owner: {q.owner}</span>
              <span>Updated 18 Sep 2026</span>
            </div>
          </div>
          <div>
            <Button onClick={() => setModal("assign")}>Assign owner</Button>
            <Button kind="primary" onClick={() => setApproved(true)}>
              {approved ? "Answer approved" : "Review proposed answer"}
            </Button>
          </div>
        </div>
        <div className="tabs">
          {["Rationale", "Evidence", "Proposed answer", "Decision history"].map(
            (t) => (
              <button
                className={tab === t ? "active" : ""}
                onClick={() => setTab(t)}
                key={t}
              >
                {t}
              </button>
            ),
          )}
        </div>
        {tab === "Rationale" && (
          <div className="rationale-grid">
            <div className="why-card">
              <span>Reach</span>
              <strong>{q.cases} cases</strong>
              <p>Cases in two related case groups may be affected.</p>
            </div>
            <div className="why-card">
              <span>Decision impact</span>
              <strong>{q.impact}</strong>
              <p>The answer could change routing or approval requirements.</p>
            </div>
            <div className="why-card">
              <span>Risk if unresolved</span>
              <strong>{q.risk}</strong>
              <p>
                Incorrect authority handling could create an adverse outcome.
              </p>
            </div>
            <div className="why-card">
              <span>Answerability</span>
              <strong>Owner identifiable</strong>
              <p>A policy owner can confirm scope and exceptions.</p>
            </div>
          </div>
        )}
        {tab === "Evidence" && (
          <div className="evidence-layout">
            <div>
              <h3>Supporting evidence</h3>
              <p>
                14 representative cases explicitly mention missing authority
                guidance. 28 additional cases share the same decision structure.
              </p>
              <button className="evidence-ref" onClick={() => setPage("Cases")}>
                <Icon name="file" />
                <span>
                  <strong>Case set · Shared ownership</strong>
                  <small>42 illustrative cases · provenance recorded</small>
                </span>
                <Icon name="chevron" />
              </button>
            </div>
            <div className="missing-box">
              <strong>Evidence still missing</strong>
              <p>
                Effective-date guidance and one superseded policy excerpt
                require confirmation.
              </p>
            </div>
          </div>
        )}
        {tab === "Proposed answer" && (
          <div className="answer-box">
            <div className="ai-label">AI-assisted synthesis · not policy</div>
            <h3>Proposed answer for owner review</h3>
            <p>
              Route shared-ownership settlements to the named authority owner
              when the required evidence set is complete. Where authority or
              evidence remains ambiguous, retain specialist human review.
            </p>
            <div className="callout">
              <strong>Human confirmation required</strong>
              <span>
                This suggestion cannot become approved policy without the
                authorised owner confirming scope, exceptions and effective
                date.
              </span>
            </div>
            <div className="answer-actions">
              <Button kind="danger" onClick={() => setTab("Decision history")}>
                Request clarification
              </Button>
              <Button kind="primary" onClick={() => setApproved(true)}>
                Approve with confirmation
              </Button>
            </div>
          </div>
        )}
        {tab === "Decision history" && (
          <div className="timeline">
            <div>
              <i />
              <strong>Proposed answer prepared</strong>
              <span>
                Evidence synthesised from 42 illustrative cases · 17 Sep
              </span>
            </div>
            <div>
              <i />
              <strong>Submitted to policy owner</strong>
              <span>In-prototype assignment only · 18 Sep</span>
            </div>
            {approved && (
              <div>
                <i />
                <strong>Approved in prototype</strong>
                <span>Scope and human-review boundary retained · just now</span>
              </div>
            )}
          </div>
        )}
      </section>
    </>
  )
}

function DecisionLogic({ setPage }: { setPage: (p: Page) => void }) {
  const [version, setVersion] = useState("Proposed v0.4")
  const [saved, setSaved] = useState(false)
  return (
    <>
      <PageTitle
        title="Decision Logic"
        description="Translate authorised answers into explicit, inspectable conditions while keeping exceptions and human judgement visible."
        actions={
          <>
            <Select label="Logic version" value={version} onChange={setVersion}>
              <option>Proposed v0.4</option>
              <option>Approved v0.3</option>
              <option>Draft v0.2</option>
            </Select>
            <Button kind="primary" onClick={() => setPage("Testing & Replay")}>
              Configure replay
            </Button>
          </>
        }
      />
      <div className="logic-layout">
        <section className="panel logic-list">
          <div className="panel-heading">
            <div>
              <h2>Logic sets</h2>
              <p>Claims Assessment</p>
            </div>
          </div>
          {[
            "Shared settlement authority",
            "Required evidence completeness",
            "Conflicting beneficiary record",
          ].map((x, i) => (
            <button className={`logic-item ${i === 0 ? "active" : ""}`} key={x}>
              <div>
                <strong>{x}</strong>
                <span>Linked question Q-00{i + 1}</span>
              </div>
              <Badge
                tone={i === 0 ? "warning" : i === 2 ? "success" : "neutral"}
              >
                {i === 0 ? version : i === 2 ? "Ready for testing" : "Draft"}
              </Badge>
            </button>
          ))}
        </section>
        <section className="panel logic-editor">
          <div className="logic-header">
            <div>
              <div className="eyebrow">Proposed logic · Not yet tested</div>
              <h2>Shared settlement authority</h2>
              <p>
                Derived from an owner-reviewed answer. Editing creates a
                proposed version.
              </p>
            </div>
            <Button onClick={() => setSaved(true)}>
              {saved ? "Draft saved" : "Save draft"}
            </Button>
          </div>
          <div className="source-answer">
            <span>Approved source answer</span>
            <strong>
              Q-001 · Who is authorised to approve a settlement when multiple
              policyholders are involved?
            </strong>
            <Button kind="ghost" onClick={() => setPage("Questions")}>
              Open question
            </Button>
          </div>
          <div className="rule-stack">
            <div className="rule-row">
              <span>WHEN</span>
              <Select label="Fact" value="Ownership type" onChange={() => {}}>
                <option>Ownership type</option>
              </Select>
              <Select label="Operator" value="equals" onChange={() => {}}>
                <option>equals</option>
              </Select>
              <Select
                label="Value"
                value="Multiple policyholders"
                onChange={() => {}}
              >
                <option>Multiple policyholders</option>
              </Select>
            </div>
            <div className="rule-row">
              <span>AND</span>
              <Select label="Fact" value="Evidence set" onChange={() => {}}>
                <option>Evidence set</option>
              </Select>
              <Select label="Operator" value="is" onChange={() => {}}>
                <option>is</option>
              </Select>
              <Select label="Value" value="Complete" onChange={() => {}}>
                <option>Complete</option>
                <option>Incomplete</option>
              </Select>
            </div>
            <Button icon="plus" onClick={() => setSaved(false)}>
              Add condition
            </Button>
          </div>
          <div className="outcomes">
            <div>
              <span>THEN</span>
              <strong>Route to the authorised settlement owner</strong>
              <p>
                Authority remains subject to the approved scope and effective
                date.
              </p>
            </div>
            <div className="exception">
              <span>EXCEPTION PATH</span>
              <strong>Specialist human review</strong>
              <p>
                Required when authority, evidence or an exception remains
                ambiguous.
              </p>
            </div>
          </div>
          <div className="version-note">
            <Icon name="branch" />
            <div>
              <strong>Version control is active</strong>
              <span>
                Changes are saved to {version}; approved v0.3 is not
                overwritten.
              </span>
            </div>
            <Button onClick={() => setSaved(true)}>Compare versions</Button>
          </div>
        </section>
      </div>
    </>
  )
}

function Testing({
  setModal,
  setPage,
}: {
  setModal: (m: Modal) => void
  setPage: (p: Page) => void
}) {
  const [filter, setFilter] = useState("All cases")
  const metrics = [
    ["120", "Cases included"],
    ["71", "Unchanged"],
    ["19", "Proposed change"],
    ["18", "Human review"],
    ["12", "Insufficient evidence"],
  ]
  return (
    <>
      <PageTitle
        title="Testing & Replay"
        description="Estimate what approved logic could change across historical cases, including unresolved and adverse outcomes."
        actions={
          <>
            <Button onClick={() => setPage("Decision Logic")}>
              View decision logic
            </Button>
            <Button
              kind="primary"
              icon="play"
              onClick={() => setModal("replay")}
            >
              Configure simulated replay
            </Button>
          </>
        }
      />
      <div className="simulation-banner">
        <Icon name="play" />
        <div>
          <strong>Illustrative simulated result</strong>
          <span>
            This design demonstration is not connected to an execution engine
            and does not show a real historical test.
          </span>
        </div>
        <Badge tone="warning">Simulation only</Badge>
      </div>
      <div className="test-summary">
        {metrics.map(([v, l], i) => (
          <button
            key={l}
            className={i === 2 ? "highlight" : ""}
            onClick={() => setFilter(l)}
          >
            <strong>{v}</strong>
            <span>{l}</span>
          </button>
        ))}
      </div>
      <div className="test-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Outcome comparison</h2>
              <p>Original handling compared with proposed routing</p>
            </div>
            <Badge tone="info">Run SIM-006</Badge>
          </div>
          <div className="comparison-bars">
            <div>
              <span>Original handling</span>
              <i>
                <b style={{ width: "62%" }} />
                <em style={{ width: "38%" }} />
              </i>
              <small>74 standard · 46 escalated</small>
            </div>
            <div>
              <span>Proposed handling</span>
              <i>
                <b style={{ width: "75%" }} />
                <em style={{ width: "25%" }} />
              </i>
              <small>90 standard · 30 review</small>
            </div>
          </div>
          <div className="legend">
            <span>
              <i className="blue" />
              Standard path
            </span>
            <span>
              <i className="amber" />
              Human review
            </span>
          </div>
          <div className="chart-note">
            <Icon name="help" />
            <span>
              Fewer escalations are not automatically better. 7 changed cases
              require policy-owner adjudication before interpretation.
            </span>
          </div>
        </section>
        <section className="panel risk-panel">
          <div className="panel-heading">
            <div>
              <h2>Evaluation cautions</h2>
              <p>What this simulation cannot establish</p>
            </div>
          </div>
          <ul>
            <li>Historical outcomes are not confirmed ground truth.</li>
            <li>The same cases informed candidate question discovery.</li>
            <li>12 cases still lack required evidence.</li>
            <li>3 proposed changes conflict with prior handling.</li>
          </ul>
          <Button kind="ghost" onClick={() => setPage("Reports")}>
            View limitations in report
          </Button>
        </section>
      </div>
      <section className="panel table-panel">
        <div className="table-toolbar">
          <h2>Case-level comparison</h2>
          <Select label="Result filter" value={filter} onChange={setFilter}>
            <option>All cases</option>
            <option>Proposed change</option>
            <option>Human review</option>
            <option>Insufficient evidence</option>
          </Select>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Original</th>
                <th>Proposed</th>
                <th>Change</th>
                <th>Reason</th>
                <th>Remaining uncertainty</th>
              </tr>
            </thead>
            <tbody>
              {cases.slice(0, 4).map((c, i) => (
                <tr key={c[0]} onClick={() => setPage("Cases")}>
                  <td>
                    <strong>{c[0]}</strong>
                  </td>
                  <td>{i % 2 ? "Human review" : "Escalated"}</td>
                  <td>{i === 2 ? "Specialist review" : "Authority owner"}</td>
                  <td>
                    <Badge tone={i === 2 ? "neutral" : "info"}>
                      {i === 2 ? "No" : "Yes"}
                    </Badge>
                  </td>
                  <td>
                    {i === 2 ? "Exception retained" : "Conditions satisfied"}
                  </td>
                  <td>
                    {i === 1
                      ? "Evidence date"
                      : i === 2
                        ? "Judgement required"
                        : "None identified"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

function Workflows({ setPage }: { setPage: (p: Page) => void }) {
  const [search, setSearch] = useState("")
  const workflows = [
    [
      "Claims Assessment",
      "Claims operations",
      "247",
      "4",
      "12",
      "Analysis complete",
    ],
    [
      "Invoice Exception Review",
      "Finance operations",
      "184",
      "3",
      "8",
      "In review",
    ],
    [
      "Customer Refund Decisions",
      "Customer operations",
      "129",
      "2",
      "5",
      "Analysing",
    ],
    [
      "Supplier Onboarding Review",
      "Procurement",
      "96",
      "2",
      "4",
      "Draft scope",
    ],
  ]
  return (
    <>
      <PageTitle
        title="Workflows"
        description="Browse bounded AI-powered business workflows under cross-case uncertainty analysis."
        actions={
          <Button
            kind="primary"
            icon="plus"
            onClick={() => setSearch("New demo workflow")}
          >
            Add demo workflow
          </Button>
        }
      />
      <section className="panel table-panel">
        <TableToolbar
          search={search}
          setSearch={setSearch}
          onFilter={() => setSearch("Claims")}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Business function</th>
                <th>Cases</th>
                <th>Patterns</th>
                <th>Questions</th>
                <th>Status</th>
                <th>Owner</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {workflows
                .filter(
                  (w) =>
                    w.join(" ").toLowerCase().includes(search.toLowerCase()) ||
                    search === "New demo workflow",
                )
                .map((w) => (
                  <tr key={w[0]} onClick={() => setPage("Overview")}>
                    <td>
                      <strong>{w[0]}</strong>
                      <span className="cell-sub">Illustrative workflow</span>
                    </td>
                    <td>{w[1]}</td>
                    <td>{w[2]}</td>
                    <td>{w[3]}</td>
                    <td>{w[4]}</td>
                    <td>
                      <Badge tone="info">{w[5]}</Badge>
                    </td>
                    <td>Maya Chen</td>
                    <td>
                      <Icon name="chevron" />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

function Reports({ setModal }: { setModal: (m: Modal) => void }) {
  const reports = [
    [
      "Workflow uncertainty overview",
      "Cross-case patterns, scope and limitations",
      "Updated today",
    ],
    [
      "Priority questions report",
      "Ranked questions and inspectable rationale",
      "Updated yesterday",
    ],
    [
      "Decision logic review",
      "Versions, authority and exception paths",
      "Updated 2 days ago",
    ],
    [
      "Testing & replay results",
      "Simulation comparison and unresolved cases",
      "Updated 2 days ago",
    ],
    [
      "Outstanding owner decisions",
      "Questions requiring authoritative input",
      "Updated 4 days ago",
    ],
  ]
  return (
    <>
      <PageTitle
        title="Reports"
        description="Prepare evidence-led summaries for operations leaders, policy owners and technical reviewers."
        actions={
          <Button
            kind="primary"
            icon="download"
            onClick={() => setModal("export")}
          >
            Configure export
          </Button>
        }
      />
      <div className="report-grid">
        {reports.map((r, i) => (
          <button
            className="report-card"
            key={r[0]}
            onClick={() => setModal("export")}
          >
            <div className="report-preview">
              <div />
              <div />
              <div />
              <span>0{i + 1}</span>
            </div>
            <Badge tone="neutral">Prototype template</Badge>
            <h3>{r[0]}</h3>
            <p>{r[1]}</p>
            <span>{r[2]}</span>
            <div className="report-link">
              Preview report <Icon name="arrow" />
            </div>
          </button>
        ))}
      </div>
    </>
  )
}

function People({ setModal }: { setModal: (m: Modal) => void }) {
  const people = [
    [
      "MC",
      "Maya Chen",
      "Claims Policy Owner",
      "4 awaiting input",
      "Active today",
    ],
    [
      "RP",
      "Ravi Patel",
      "Compliance Reviewer",
      "2 awaiting input",
      "Active yesterday",
    ],
    [
      "EO",
      "Elena Ortiz",
      "Customer Operations Process Owner",
      "1 awaiting input",
      "Active 3 days ago",
    ],
    [
      "JW",
      "Jonas Webb",
      "Finance Operations Lead",
      "3 awaiting input",
      "Active 4 days ago",
    ],
  ]
  return (
    <>
      <PageTitle
        title="People & Ownership"
        description="Identify who has the authority to answer each question, not simply who is available."
        actions={
          <Button kind="primary" onClick={() => setModal("assign")}>
            Assign question owner
          </Button>
        }
      />
      <div className="people-grid">
        {people.map((p) => (
          <button
            className="person-card"
            key={p[1]}
            onClick={() => setModal("assign")}
          >
            <div className="avatar large">{p[0]}</div>
            <div>
              <h3>{p[1]}</h3>
              <p>{p[2]}</p>
              <span>Illustrative role</span>
            </div>
            <div className="person-stats">
              <strong>{p[3]}</strong>
              <span>{p[4]}</span>
            </div>
            <Icon name="chevron" />
          </button>
        ))}
      </div>
    </>
  )
}

function SimplePage({ page }: { page: Page }) {
  const [saved, setSaved] = useState(false)
  return (
    <>
      <PageTitle
        title={page}
        description={
          page === "Settings"
            ? "Manage restrained workspace and display preferences for this prototype."
            : "Learn how PayReality moves from case evidence to prioritised questions and tested decision logic."
        }
      />
      <section className="panel simple-settings">
        <div>
          <h2>
            {page === "Settings" ? "Workspace preferences" : "Product guide"}
          </h2>
          <p>
            {page === "Settings"
              ? "These controls affect only the local prototype state."
              : "PayReality is intended to discover the smallest, highest-value set of questions that can resolve recurring uncertainty across many business decisions."}
          </p>
        </div>
        {page === "Settings" ? (
          <>
            <label>
              Workspace name
              <input defaultValue="Northstar Labs" />
            </label>
            <label>
              Default workflow
              <select defaultValue="Claims Assessment">
                <option>Claims Assessment</option>
                <option>Invoice Exception Review</option>
              </select>
            </label>
            <label className="toggle-row">
              <span>
                <strong>In-prototype notifications</strong>
                <small>
                  Show assignment and approval feedback in this demonstration.
                </small>
              </span>
              <input type="checkbox" defaultChecked />
            </label>
            <Button kind="primary" onClick={() => setSaved(true)}>
              {saved ? "Preferences saved" : "Save preferences"}
            </Button>
          </>
        ) : (
          <div className="guide-steps">
            {[
              "Analyse cases and context",
              "Map recurring uncertainty",
              "Discover and rank questions",
              "Obtain authoritative answers",
              "Construct explicit logic",
              "Replay and evaluate",
            ].map((s, i) => (
              <div key={s}>
                <span>{i + 1}</span>
                <strong>{s}</strong>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}

function CaseDrawer({
  id,
  close,
  setPage,
}: {
  id: string
  close: () => void
  setPage: (p: Page) => void
}) {
  const [tab, setTab] = useState("Summary")
  const [noted, setNoted] = useState(false)
  return (
    <div className="overlay" onMouseDown={close}>
      <aside className="drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="eyebrow">Illustrative case</div>
            <h2>{id}</h2>
            <p>Claims Assessment · Settlement approval</p>
          </div>
          <button className="icon-btn" title="Close case" onClick={close}>
            <Icon name="close" />
          </button>
        </div>
        <div className="tabs">
          {["Summary", "Evidence", "Uncertainty", "Timeline"].map((t) => (
            <button
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
              key={t}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "Summary" && (
          <div className="drawer-content">
            <div className="status-grid">
              <div>
                <span>Disposition</span>
                <strong>Escalated</strong>
              </div>
              <div>
                <span>Review status</span>
                <strong>Needs review</strong>
              </div>
              <div>
                <span>Case date</span>
                <strong>18 Sep 2026</strong>
              </div>
              <div>
                <span>Evidence items</span>
                <strong>6 available · 2 missing</strong>
              </div>
            </div>
            <div className="content-block">
              <h3>Decision being made</h3>
              <p>
                Determine the appropriate authority path for a settlement
                involving multiple policyholders.
              </p>
            </div>
            <div className="content-block">
              <h3>Analytical interpretation</h3>
              <p>
                The workflow could not identify a single authorised approver
                from the available evidence. This interpretation is separate
                from source evidence and remains reviewable.
              </p>
            </div>
          </div>
        )}
        {tab === "Evidence" && (
          <div className="drawer-content">
            <div className="evidence-source">
              <Badge tone="success">Source evidence</Badge>
              <strong>Ownership record</strong>
              <p>
                Two policyholders are listed. Authority documentation is not
                present in the case set.
              </p>
              <small>Sample case record · 18 Sep 2026</small>
            </div>
            <div className="evidence-source">
              <Badge tone="warning">Missing evidence</Badge>
              <strong>Authority confirmation</strong>
              <p>No effective authority instrument is attached.</p>
            </div>
          </div>
        )}
        {tab === "Uncertainty" && (
          <div className="drawer-content">
            <div className="content-block">
              <h3>Known</h3>
              <p>
                Multiple policyholders are recorded and the evidence set is
                incomplete.
              </p>
            </div>
            <div className="content-block">
              <h3>Unknown</h3>
              <p>
                Which party has authority under these specific conditions and
                which exceptions apply.
              </p>
            </div>
            <div className="content-block">
              <h3>Cross-case relevance</h3>
              <p>41 other illustrative cases share the candidate pattern.</p>
            </div>
          </div>
        )}
        {tab === "Timeline" && (
          <div className="drawer-content timeline">
            <div>
              <i />
              <strong>Case received</strong>
              <span>09:12 · Evidence set recorded</span>
            </div>
            <div>
              <i />
              <strong>Workflow assessment paused</strong>
              <span>09:14 · Authority could not be established</span>
            </div>
            <div>
              <i />
              <strong>Human review requested</strong>
              <span>09:18 · Final disposition pending</span>
            </div>
          </div>
        )}
        <div className="drawer-footer">
          <Button onClick={() => setNoted(true)}>
            {noted ? "Note added" : "Add note"}
          </Button>
          <Button
            onClick={() => {
              close()
              setPage("Patterns")
            }}
          >
            View pattern
          </Button>
          <Button
            kind="primary"
            onClick={() => {
              close()
              setPage("Questions")
            }}
          >
            Open related question
          </Button>
        </div>
      </aside>
    </div>
  )
}

function ModalLayer({
  modal,
  close,
  setPage,
}: {
  modal: Modal
  close: () => void
  setPage: (p: Page) => void
}) {
  const [step, setStep] = useState(1)
  const [query, setQuery] = useState("")
  const [saved, setSaved] = useState(false)
  if (!modal) return null
  const title =
    modal === "search"
      ? "Search PayReality"
      : modal === "export"
        ? "Export report"
        : modal === "new-question"
          ? "Create candidate question"
          : modal === "assign"
            ? "Assign authoritative owner"
            : modal === "replay"
              ? "Configure simulated replay"
              : "Notifications"
  return (
    <div className="overlay modal-overlay" onMouseDown={close}>
      <div
        className={`modal ${modal === "search" ? "search-modal" : ""}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <div className="eyebrow">Prototype interaction</div>
            <h2>{title}</h2>
          </div>
          <button className="icon-btn" title="Close dialog" onClick={close}>
            <Icon name="close" />
          </button>
        </div>
        {modal === "search" && (
          <div>
            <label className="modal-search">
              <Icon name="search" />
              <input
                autoFocus
                placeholder="Search cases, patterns, questions…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="search-filters">
              <Badge tone="info">All</Badge>
              <Badge>Cases</Badge>
              <Badge>Patterns</Badge>
              <Badge>Questions</Badge>
            </div>
            <div className="search-results">
              {[
                ["Patterns", "Settlement authority is unclear"],
                ["Questions", questions[0].question],
                ["Cases", "CLM-10482 · Settlement approval"],
              ]
                .filter((x) =>
                  x.join(" ").toLowerCase().includes(query.toLowerCase()),
                )
                .map((x) => (
                  <button
                    key={x[1]}
                    onClick={() => {
                      close()
                      setPage(x[0] as Page)
                    }}
                  >
                    <span>{x[0]}</span>
                    <strong>{x[1]}</strong>
                    <Icon name="chevron" />
                  </button>
                ))}
            </div>
          </div>
        )}
        {modal === "notifications" && (
          <div className="notification-list">
            {[
              [
                "Owner input requested",
                "Question Q-001 is awaiting policy review.",
              ],
              [
                "Evidence conflict found",
                "Two excerpts may apply to pattern PAT-003.",
              ],
              ["Simulation ready", "Illustrative run SIM-006 can be reviewed."],
            ].map((x, i) => (
              <button
                key={x[0]}
                onClick={() => {
                  close()
                  setPage(
                    i === 2
                      ? "Testing & Replay"
                      : i === 1
                        ? "Patterns"
                        : "Questions",
                  )
                }}
              >
                <i />
                <div>
                  <strong>{x[0]}</strong>
                  <span>{x[1]}</span>
                </div>
                <Icon name="chevron" />
              </button>
            ))}
          </div>
        )}
        {modal === "export" && (
          <div className="form-body">
            <label>
              Report type
              <select>
                <option>Priority questions report</option>
                <option>Workflow uncertainty overview</option>
                <option>Testing & replay results</option>
              </select>
            </label>
            <label>
              Format
              <div className="radio-group">
                <span>
                  <input type="radio" name="format" defaultChecked /> PDF
                  preview
                </span>
                <span>
                  <input type="radio" name="format" /> CSV sample
                </span>
              </div>
            </label>
            <label className="toggle-row">
              <span>
                <strong>Include limitations</strong>
                <small>Add evidence gaps and prototype caveats.</small>
              </span>
              <input type="checkbox" defaultChecked />
            </label>
            {saved && (
              <div className="success">
                <Icon name="check" />
                <span>
                  <strong>Export request simulated</strong>This prototype has
                  not generated or downloaded a real file.
                </span>
              </div>
            )}
          </div>
        )}
        {modal === "new-question" && (
          <div className="form-body">
            <label>
              Question text *
              <textarea placeholder="What authoritative answer could resolve this recurring uncertainty?" />
            </label>
            <div className="form-grid">
              <label>
                Related workflow
                <select>
                  <option>Claims Assessment</option>
                </select>
              </label>
              <label>
                Related pattern
                <select>
                  <option>Settlement authority is unclear</option>
                </select>
              </label>
            </div>
            <label>
              Why it may matter
              <textarea placeholder="Describe the cases and decisions potentially affected." />
            </label>
            <label>
              Proposed owner
              <select>
                <option>Unassigned</option>
                <option>Maya Chen · Claims Policy Owner</option>
              </select>
            </label>
            {saved && (
              <div className="success">
                <Icon name="check" />
                <span>
                  <strong>Draft added to local state</strong>The candidate
                  remains unapproved.
                </span>
              </div>
            )}
          </div>
        )}
        {modal === "assign" && (
          <div className="form-body">
            <div className="callout">
              <strong>Authority matters</strong>
              <span>
                Choose the person accountable for confirming policy, not simply
                a task assignee.
              </span>
            </div>
            <label>
              Authoritative owner
              <select>
                <option>Maya Chen · Claims Policy Owner</option>
                <option>Ravi Patel · Compliance Reviewer</option>
                <option>Elena Ortiz · Process Owner</option>
              </select>
            </label>
            <label>
              Review note
              <textarea defaultValue="Please confirm the applicable scope, exceptions and effective date." />
            </label>
            {saved && (
              <div className="success">
                <Icon name="check" />
                <span>
                  <strong>Owner assigned in prototype</strong>No external
                  notification was sent.
                </span>
              </div>
            )}
          </div>
        )}
        {modal === "replay" && (
          <div className="form-body">
            <div className="stepper">
              {["Workflow", "Logic", "Case set", "Review"].map((x, i) => (
                <span className={step >= i + 1 ? "active" : ""} key={x}>
                  <i>{i + 1}</i>
                  {x}
                </span>
              ))}
            </div>
            {step === 1 && (
              <label>
                Workflow
                <select>
                  <option>Claims Assessment</option>
                </select>
              </label>
            )}
            {step === 2 && (
              <label>
                Approved decision logic
                <select>
                  <option>Shared settlement authority · v0.3</option>
                </select>
              </label>
            )}
            {step === 3 && (
              <>
                <label>
                  Historical case set
                  <select>
                    <option>Shared ownership cases · 120 records</option>
                  </select>
                </label>
                <div className="callout">
                  <strong>Evaluation criteria</strong>
                  <span>
                    Consistency, unresolved uncertainty, human review and
                    adverse changes.
                  </span>
                </div>
              </>
            )}
            {step === 4 && (
              <div className="review-config">
                <strong>Ready to simulate</strong>
                <p>Claims Assessment · Logic v0.3 · 120 illustrative cases</p>
                <p>No real data or execution engine is connected.</p>
              </div>
            )}
          </div>
        )}
        {modal !== "search" && modal !== "notifications" && (
          <div className="modal-footer">
            <Button onClick={close}>Cancel</Button>
            {modal === "replay" && step < 4 ? (
              <Button kind="primary" onClick={() => setStep(step + 1)}>
                Continue
              </Button>
            ) : (
              <Button
                kind="primary"
                onClick={() => {
                  if (modal === "replay") {
                    close()
                    setPage("Testing & Replay")
                  } else setSaved(true)
                }}
              >
                {modal === "replay"
                  ? "Run prototype simulation"
                  : modal === "export"
                    ? "Request export"
                    : "Save"}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState<Page>("Overview")
  const [collapsed, setCollapsed] = useState(false)
  const [modal, setModal] = useState<Modal>(null)
  const [drawerCase, setDrawerCase] = useState<string | null>(null)
  const [workflow, setWorkflow] = useState("Claims Assessment")
  const [period, setPeriod] = useState("Last 90 days")
  const content = useMemo(() => {
    if (page === "Overview")
      return (
        <Overview
          setPage={setPage}
          setModal={setModal}
          period={period}
          setPeriod={setPeriod}
        />
      )
    if (page === "Workflows") return <Workflows setPage={setPage} />
    if (page === "Cases") return <Cases openCase={setDrawerCase} />
    if (page === "Patterns") return <Patterns setPage={setPage} />
    if (page === "Questions")
      return <Questions setModal={setModal} setPage={setPage} />
    if (page === "Decision Logic") return <DecisionLogic setPage={setPage} />
    if (page === "Testing & Replay")
      return <Testing setModal={setModal} setPage={setPage} />
    if (page === "Reports") return <Reports setModal={setModal} />
    if (page === "People & Ownership") return <People setModal={setModal} />
    return <SimplePage page={page} />
  }, [page, period])
  return (
    <div className="app-shell">
      <Sidebar
        page={page}
        setPage={setPage}
        collapsed={collapsed}
        setCollapsed={setCollapsed}
      />
      <div className="app-main">
        <Topbar
          page={page}
          setModal={setModal}
          workflow={workflow}
          setWorkflow={setWorkflow}
        />
        <main>{content}</main>
      </div>
      {drawerCase && (
        <CaseDrawer
          id={drawerCase}
          close={() => setDrawerCase(null)}
          setPage={setPage}
        />
      )}
      <ModalLayer
        modal={modal}
        close={() => setModal(null)}
        setPage={setPage}
      />
    </div>
  )
}
