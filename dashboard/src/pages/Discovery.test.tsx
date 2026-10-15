import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { SuggestionCard } from "./Discovery"
import { decisionIntelligenceApi } from "../di/api"
import type { DiscoverySuggestion } from "../di/types"

vi.mock("../di/api", () => ({
  decisionIntelligenceApi: {
    acceptSuggestion: vi.fn(),
    dismissSuggestion: vi.fn(),
  },
}))

function makeSuggestion(overrides: Partial<DiscoverySuggestion> = {}): DiscoverySuggestion {
  return {
    id: "sugg-1",
    discovery_run_id: "run-1",
    kind: "pattern",
    title: "Unclear policy on photo evidence",
    description: "Two near-identical cases were resolved in opposite directions.",
    supporting_case_ids: ["case-1", "case-2"],
    rationale: "Both cases share the same amount band and missing-evidence shape.",
    confidence: "medium",
    category: "unclear_policy",
    linked_pattern_id: null,
    status: "suggested",
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("Discovery suggestion review: accept/dismiss updates real UI state from the mocked API response", () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it("renders a pending suggestion as AI-suggested, distinct from an authoritative entity", () => {
    render(
      <SuggestionCard suggestion={makeSuggestion()} canAct={true} openCase={() => {}} setPage={() => {}} onUpdated={() => {}} />,
    )
    expect(screen.getByText("AI suggested: awaiting review")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument()
  })

  it("accepting calls the real accept endpoint, shows the real created entity, and reports 'accepted' to the parent", async () => {
    const onUpdated = vi.fn()
    const setPage = vi.fn()
    vi.mocked(decisionIntelligenceApi.acceptSuggestion).mockResolvedValue({
      entity_type: "pattern",
      pattern: {
        id: "pattern-123",
        organization_id: "org-1",
        workflow_id: "wf-1",
        name: "Unclear policy on photo evidence",
        description: "desc",
        category: "unclear_policy",
        proposed_explanation: "x",
        alternative_explanations: null,
        confidence: "medium",
        review_status: "proposed",
        created_by_user_id: "user-1",
        created_at: "now",
        updated_at: "now",
      },
      question: null,
    })

    render(
      <SuggestionCard suggestion={makeSuggestion()} canAct={true} openCase={() => {}} setPage={setPage} onUpdated={onUpdated} />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Accept" }))

    await waitFor(() => expect(screen.getByText(/Created pattern/)).toBeInTheDocument())
    expect(screen.getAllByText(/Unclear policy on photo evidence/)).toHaveLength(2) // the card's own title, plus the success message naming the real created entity
    expect(decisionIntelligenceApi.acceptSuggestion).toHaveBeenCalledWith("sugg-1")
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: "sugg-1", status: "accepted" }))

    fireEvent.click(screen.getByRole("button", { name: /View Patterns/ }))
    expect(setPage).toHaveBeenCalledWith("Patterns")
  })

  it("dismissing calls the real dismiss endpoint and, once the parent re-renders with the updated status, hides the action buttons and the AI-suggested label", async () => {
    const onUpdated = vi.fn()
    const dismissed = makeSuggestion({ status: "dismissed" })
    vi.mocked(decisionIntelligenceApi.dismissSuggestion).mockResolvedValue(dismissed)

    const { rerender } = render(
      <SuggestionCard suggestion={makeSuggestion()} canAct={true} openCase={() => {}} setPage={() => {}} onUpdated={onUpdated} />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))

    await waitFor(() => expect(decisionIntelligenceApi.dismissSuggestion).toHaveBeenCalledWith("sugg-1"))
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "dismissed" }))

    // The real parent (Discovery.tsx) applies onUpdated's result back into
    // props on its next render -- simulate exactly that here.
    rerender(<SuggestionCard suggestion={dismissed} canAct={true} openCase={() => {}} setPage={() => {}} onUpdated={onUpdated} />)

    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument()
    expect(screen.queryByText("AI suggested: awaiting review")).not.toBeInTheDocument()
    expect(screen.getByText("dismissed")).toBeInTheDocument()
  })
})
