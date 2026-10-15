import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import App from "./App"

const SESSION_KEY = "payreality_di_dashboard_session_token"

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response)
}

const CURRENT_USER = {
  id: "user-1",
  organization_id: "org-1",
  email: "owner@example.com",
  name: "Owner Example",
  role: "owner",
  status: "active",
  mfa_enabled: false,
  must_reset_password: false,
  last_login_at: null,
  permissions: ["di_question.view", "di_case.view"],
}

describe("the login gate", () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it("shows the login screen when there is no session token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => jsonResponse({ detail: "not called" }, 500)),
    )
    render(<App />)
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument())
  })

  it("shows the dashboard once a valid session token resolves via /v1/auth/me", async () => {
    localStorage.setItem(SESSION_KEY, "a-real-looking-token")
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      if (url.endsWith("/v1/auth/me")) return jsonResponse(CURRENT_USER)
      if (url.includes("/v1/decision-intelligence/workflows")) {
        return jsonResponse({ workflows: [], total: 0, limit: 200, offset: 0 })
      }
      return jsonResponse({}, 404)
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument())
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/auth/me"),
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
  })
})
