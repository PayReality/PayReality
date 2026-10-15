import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { AnswerPanel } from "./Questions"
import type { Answer } from "../di/types"

function makeAnswer(overrides: Partial<Answer> = {}): Answer {
  return {
    id: "answer-1",
    question_id: "question-1",
    content: "Route to the named authority owner.",
    evidence_refs: null,
    scope: null,
    conditions_exceptions: null,
    effective_date: null,
    review_date: null,
    version: 1,
    previous_version_id: null,
    author_user_id: "user-author",
    approver_user_id: null,
    status: "submitted",
    disposition: null,
    disposition_notes: null,
    submitted_at: new Date().toISOString(),
    decided_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("AnswerPanel separation-of-duties block", () => {
  it("disables Approve and explains why when the current user authored the submitted answer", () => {
    const answer = makeAnswer({ author_user_id: "same-user" })
    render(
      <AnswerPanel
        questionId="question-1"
        answers={[answer]}
        reload={() => {}}
        currentUserId="same-user"
        canSubmit={false}
        canApprove={true}
      />,
    )
    expect(screen.getByText(/You authored this answer, so you cannot also approve it/)).toBeInTheDocument()
    const approveButton = screen.getByRole("button", { name: /Cannot approve your own answer/ })
    expect(approveButton).toBeDisabled()
  })

  it("leaves Approve enabled when a different user is approving", () => {
    const answer = makeAnswer({ author_user_id: "author-user" })
    render(
      <AnswerPanel
        questionId="question-1"
        answers={[answer]}
        reload={() => {}}
        currentUserId="reviewer-user"
        canSubmit={false}
        canApprove={true}
      />,
    )
    expect(screen.queryByText(/You authored this answer/)).not.toBeInTheDocument()
    const approveButton = screen.getByRole("button", { name: "Approve" })
    expect(approveButton).not.toBeDisabled()
  })
})
