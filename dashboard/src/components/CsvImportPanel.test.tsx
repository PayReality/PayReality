import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { CsvImportPanel } from "./CsvImportPanel"
import { decisionIntelligenceApi } from "../di/api"
import type { ImportJob } from "../di/types"

vi.mock("../di/api", () => ({
  decisionIntelligenceApi: {
    createImportJob: vi.fn(),
    listImportJobs: vi.fn(),
  },
}))

function makeFile(content: string, name = "cases.csv"): File {
  return new File([content], name, { type: "text/csv" })
}

describe("CsvImportPanel handles a real backend response with mixed valid/invalid rows", () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it("parses headers, lets the user map columns, uploads, and renders the per-row errors for invalid rows", async () => {
    const onImported = vi.fn()
    const jobResponse: ImportJob = {
      id: "job-1",
      organization_id: "org-1",
      workflow_id: "wf-1",
      status: "completed",
      filename: "cases.csv",
      total_rows: 3,
      valid_rows: 2,
      invalid_rows: 1,
      row_errors: [{ row_number: 2, errors: ["invalid_human_decision_json: row 2 column 'Decision': not valid JSON"] }],
      created_by_user_id: "user-1",
      created_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    }
    vi.mocked(decisionIntelligenceApi.createImportJob).mockResolvedValue(jobResponse)

    render(<CsvImportPanel workflowId="wf-1" onImported={onImported} />)

    const csvText = ['Ref,Decision,Amount', 'CLM-1,"{""decision"":""approve""}",100', "CLM-2,not-json,200", 'CLM-3,"{""decision"":""deny""}",300'].join(
      "\n",
    )
    const input = screen.getByLabelText(/CSV file/i) as HTMLInputElement
    fireEvent.change(input, { target: { files: [makeFile(csvText)] } })

    // Header row parsed client-side, mapping UI rendered.
    await screen.findByText("Ref")
    expect(screen.getByText("Decision")).toBeInTheDocument()
    expect(screen.getByText("Amount")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /Upload and import/ }))

    await waitFor(() => expect(decisionIntelligenceApi.createImportJob).toHaveBeenCalledTimes(1))
    const [workflowId, file, mapping] = vi.mocked(decisionIntelligenceApi.createImportJob).mock.calls[0]
    expect(workflowId).toBe("wf-1")
    expect(file.name).toBe("cases.csv")
    expect(mapping).toEqual({ Ref: "facts", Decision: "facts", Amount: "facts" })

    // The real job summary: counts plus the specific per-row error, not
    // just a total. "2" appears twice by design here -- once as the valid
    // row count, once as the failing row's row_number -- so both real
    // occurrences are asserted directly rather than papered over.
    await waitFor(() => expect(screen.getAllByText("2")).toHaveLength(2))
    expect(screen.getByText("3")).toBeInTheDocument() // total_rows
    expect(screen.getByText("1")).toBeInTheDocument() // invalid_rows
    expect(screen.getByText(/invalid_human_decision_json/)).toBeInTheDocument()
    expect(onImported).toHaveBeenCalledTimes(1)
  })

  it("rejects a non-.csv file client-side before ever calling the backend", async () => {
    render(<CsvImportPanel workflowId="wf-1" onImported={() => {}} />)
    const input = screen.getByLabelText(/CSV file/i) as HTMLInputElement
    fireEvent.change(input, { target: { files: [makeFile("not a csv", "cases.txt")] } })

    await screen.findByText(/Only \.csv files are supported/)
    expect(decisionIntelligenceApi.createImportJob).not.toHaveBeenCalled()
  })
})
