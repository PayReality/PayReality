import { useEffect, useState } from "react"
import { AuthProvider, useAuth } from "./auth/AuthContext"
import { LoginPage } from "./auth/LoginPage"
import { Sidebar } from "./components/Sidebar"
import { Topbar } from "./components/Topbar"
import { CaseDrawer } from "./components/CaseDrawer"
import { ModalLayer } from "./components/ModalLayer"
import { Overview } from "./pages/Overview"
import { Workflows } from "./pages/Workflows"
import { Cases } from "./pages/Cases"
import { Patterns } from "./pages/Patterns"
import { Discovery } from "./pages/Discovery"
import { Questions } from "./pages/Questions"
import { DecisionLogic } from "./pages/DecisionLogic"
import { Testing } from "./pages/Testing"
import { Reports } from "./pages/Reports"
import { People } from "./pages/People"
import { SimplePage } from "./pages/SimplePage"
import { decisionIntelligenceApi } from "./di/api"
import { usersApi } from "./users/api"
import type { Workflow, WorkflowOverview } from "./di/types"
import type { OrgUser } from "./users/types"
import type { Modal, Page } from "./types"

function Dashboard() {
  const { hasPermission } = useAuth()
  const [page, setPage] = useState<Page>("Overview")
  const [collapsed, setCollapsed] = useState(false)
  const [modal, setModal] = useState<Modal>(null)
  const [drawerCase, setDrawerCase] = useState<string | null>(null)
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [workflowId, setWorkflowId] = useState<string | null>(null)
  const [workflowsVersion, setWorkflowsVersion] = useState(0)
  const [orgUsers, setOrgUsers] = useState<OrgUser[] | null>(null)
  const [overview, setOverview] = useState<WorkflowOverview | null>(null)
  const [questionsRefreshKey, setQuestionsRefreshKey] = useState(0)
  const canManageUsers = hasPermission("users.manage")

  useEffect(() => {
    decisionIntelligenceApi.listWorkflows({ limit: 200 }).then((p) => {
      setWorkflows(p.workflows)
      setWorkflowId((current) => (current && p.workflows.some((w) => w.id === current) ? current : (p.workflows[0]?.id ?? null)))
    })
  }, [workflowsVersion])

  useEffect(() => {
    if (!canManageUsers) {
      setOrgUsers(null)
      return
    }
    usersApi
      .list()
      .then(setOrgUsers)
      .catch(() => setOrgUsers(null))
  }, [canManageUsers])

  useEffect(() => {
    if (!workflowId) {
      setOverview(null)
      return
    }
    let cancelled = false
    decisionIntelligenceApi
      .getWorkflowOverview(workflowId)
      .then((o) => !cancelled && setOverview(o))
      .catch(() => !cancelled && setOverview(null))
    return () => {
      cancelled = true
    }
  }, [workflowId, questionsRefreshKey])

  function reloadWorkflows() {
    setWorkflowsVersion((v) => v + 1)
  }

  const questionsAwaitingAnswer = overview?.questions_by_status["awaiting_answer"] ?? null

  let content: React.ReactNode
  if (page === "Overview") content = <Overview workflowId={workflowId} setPage={setPage} setModal={setModal} />
  else if (page === "Workflows") content = <Workflows workflows={workflows} onCreated={reloadWorkflows} setWorkflowId={setWorkflowId} />
  else if (page === "Cases") content = <Cases workflowId={workflowId} openCase={setDrawerCase} />
  else if (page === "Patterns") content = <Patterns workflowId={workflowId} setPage={setPage} />
  else if (page === "Discovery") content = <Discovery workflowId={workflowId} setPage={setPage} openCase={setDrawerCase} />
  else if (page === "Questions")
    content = (
      <Questions
        workflowId={workflowId}
        setModal={setModal}
        setPage={setPage}
        orgUsers={orgUsers}
        totalCases={overview?.case_count ?? null}
        refreshKey={questionsRefreshKey}
      />
    )
  else if (page === "Decision Logic") content = <DecisionLogic workflowId={workflowId} setPage={setPage} />
  else if (page === "Testing & Replay") content = <Testing workflowId={workflowId} setPage={setPage} />
  else if (page === "Reports") content = <Reports workflowId={workflowId} />
  else if (page === "People & Ownership") content = <People />
  else content = <SimplePage page={page} />

  return (
    <div className="app-shell">
      <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} questionsAwaitingAnswer={questionsAwaitingAnswer} />
      <div className="app-main">
        <Topbar page={page} setModal={setModal} workflows={workflows} workflowId={workflowId} setWorkflowId={setWorkflowId} />
        <main>{content}</main>
      </div>
      {drawerCase && <CaseDrawer id={drawerCase} close={() => setDrawerCase(null)} setPage={setPage} />}
      <ModalLayer
        modal={modal}
        close={() => setModal(null)}
        setPage={setPage}
        workflowId={workflowId}
        orgUsers={orgUsers}
        onQuestionCreated={() => setQuestionsRefreshKey((k) => k + 1)}
      />
    </div>
  )
}

function Gate() {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 13 }}>
        Loading…
      </div>
    )
  }
  if (!user) return <LoginPage />
  return <Dashboard />
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
