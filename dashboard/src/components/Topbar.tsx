import { useState } from "react"
import { Icon, Select } from "./ui"
import type { Modal, Page } from "../types"
import type { Workflow } from "../di/types"
import { useAuth } from "../auth/AuthContext"

export function Topbar({
  page,
  setModal,
  workflows,
  workflowId,
  setWorkflowId,
}: {
  page: Page
  setModal: (m: Modal) => void
  workflows: Workflow[]
  workflowId: string | null
  setWorkflowId: (v: string) => void
}) {
  const [profile, setProfile] = useState(false)
  const { user, logout } = useAuth()
  const currentWorkflow = workflows.find((w) => w.id === workflowId)
  return (
    <header className="topbar">
      <div className="crumbs">
        <span>{currentWorkflow?.name ?? "No workflow"}</span>
        <Icon name="chevron" size={13} />
        <strong>{page}</strong>
      </div>
      <div className="top-actions">
        {workflows.length > 0 ? (
          <Select label="Selected workflow" value={workflowId ?? ""} onChange={setWorkflowId}>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </Select>
        ) : (
          <span className="workflow-empty-select">No workflows yet</span>
        )}
        <button className="search-trigger" onClick={() => setModal("search")} disabled={!workflowId}>
          <Icon name="search" size={16} />
          <span>Search this workflow…</span>
          <kbd>⌘ K</kbd>
        </button>
        <button className="icon-btn notification" title="Notifications" onClick={() => setModal("notifications-info")}>
          <Icon name="bell" />
        </button>
        <div className="profile-wrap">
          <button className="avatar top-avatar" title="Open profile menu" onClick={() => setProfile(!profile)}>
            {user ? user.name.slice(0, 2).toUpperCase() : "?"}
          </button>
          {profile && (
            <div className="menu">
              <button onClick={() => setProfile(false)}>{user?.email}</button>
              <button
                onClick={() => {
                  setProfile(false)
                  void logout()
                }}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
