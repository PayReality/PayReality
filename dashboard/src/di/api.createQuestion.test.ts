import { afterEach, describe, expect, it, vi } from "vitest"
import { decisionIntelligenceApi } from "./api"
import { setSessionToken, clearSessionToken } from "../lib/session"

function jsonResponse(body: unknown, status = 201) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response)
}

describe("createQuestion full mocked-fetch round trip", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearSessionToken()
  })

  it("POSTs the real request shape with the Bearer token, and returns the parsed real response", async () => {
    setSessionToken("test-session-token")
    const created = {
      id: "question-1",
      organization_id: "org-1",
      workflow_id: "workflow-1",
      title: "Who approves a shared-ownership settlement?",
      description: "Why it matters",
      status: "proposed",
      reach_score: null,
      impact_score: null,
      risk_score: null,
      answerability_score: null,
      decision_sensitivity_score: null,
      priority_score: null,
      scoring_version: null,
      owner_user_id: null,
      created_by_user_id: "user-1",
      created_at: "2026-10-15T00:00:00Z",
      updated_at: "2026-10-15T00:00:00Z",
    }
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse(created))
    vi.stubGlobal("fetch", fetchMock)

    const result = await decisionIntelligenceApi.createQuestion({
      workflow_id: "workflow-1",
      title: created.title,
      description: created.description,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain("/v1/decision-intelligence/questions")
    expect(init?.method).toBe("POST")
    expect(JSON.parse(init?.body as string)).toEqual({
      workflow_id: "workflow-1",
      title: created.title,
      description: created.description,
    })
    const headers = init?.headers as Headers
    expect(headers.get("Authorization")).toBe("Bearer test-session-token")
    expect(headers.get("Content-Type")).toBe("application/json")

    // The real response round-trips back out, including the backend's
    // own null-priority-score contract -- never fabricated.
    expect(result).toEqual(created)
    expect(result.priority_score).toBeNull()
  })
})
