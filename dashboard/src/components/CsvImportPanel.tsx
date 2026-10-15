import { useState } from "react"
import { Badge, Button, ErrorNote, Icon } from "./ui"
import { decisionIntelligenceApi } from "../di/api"
import type { ColumnMappingTarget, ImportJob } from "../di/types"
import { errorMessage, useFetch } from "../lib/useAsync"

// The five real DICase fields a column can map to (csv_import.py's own
// TARGET_FIELDS), plus the literal "exclude" target. "facts" is this
// panel's own default for every column, matching the backend's documented
// default for any header NOT present in column_mapping at all.
export const MAPPING_OPTIONS: { value: ColumnMappingTarget; label: string }[] = [
  { value: "facts", label: "Keep as a facts key" },
  { value: "external_ref", label: "External reference" },
  { value: "human_decision", label: "Recorded baseline decision (JSON)" },
  { value: "escalation_reason", label: "Escalation reason" },
  { value: "outcome", label: "Outcome" },
  { value: "exclude", label: "Ignore this column" },
]

// Only parses the CSV's header row, client-side, to drive the
// column-mapping UI -- every real row is validated and imported by the
// backend (csv_import.py), never re-implemented here. A minimal
// quote-aware splitter is enough for a header line.
export function parseCsvHeaderLine(text: string): string[] {
  const firstLine = text.split(/\r\n|\n|\r/)[0] ?? ""
  const result: string[] = []
  let cur = ""
  let inQuotes = false
  for (let i = 0; i < firstLine.length; i++) {
    const ch = firstLine[i]
    if (ch === '"') {
      inQuotes = !inQuotes
      continue
    }
    if (ch === "," && !inQuotes) {
      result.push(cur)
      cur = ""
      continue
    }
    cur += ch
  }
  result.push(cur)
  return result.map((h) => h.trim()).filter((h) => h.length > 0)
}

export function CsvImportPanel({ workflowId, onImported }: { workflowId: string; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[] | null>(null)
  const [mapping, setMapping] = useState<Record<string, ColumnMappingTarget>>({})
  const [parseError, setParseError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportJob | null>(null)
  const [showPastImports, setShowPastImports] = useState(false)

  const pastImports = useFetch(
    () =>
      showPastImports
        ? decisionIntelligenceApi.listImportJobs({ workflow_id: workflowId, limit: 50 })
        : Promise.resolve(null),
    [showPastImports, workflowId],
  )

  async function handleFile(selected: File | null) {
    setFile(selected)
    setHeaders(null)
    setMapping({})
    setParseError(null)
    setUploadError(null)
    setResult(null)
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith(".csv")) {
      setParseError("Only .csv files are supported.")
      return
    }
    try {
      const text = await selected.text()
      const parsedHeaders = parseCsvHeaderLine(text)
      if (parsedHeaders.length === 0) {
        setParseError("Couldn't find a header row in this file.")
        return
      }
      setHeaders(parsedHeaders)
      const initialMapping: Record<string, ColumnMappingTarget> = {}
      for (const h of parsedHeaders) initialMapping[h] = "facts"
      setMapping(initialMapping)
    } catch {
      setParseError("Couldn't read this file.")
    }
  }

  async function submit() {
    if (!file) return
    setUploading(true)
    setUploadError(null)
    try {
      const job = await decisionIntelligenceApi.createImportJob(workflowId, file, mapping)
      setResult(job)
      if (job.valid_rows > 0) onImported()
      if (showPastImports) pastImports.reload()
    } catch (err) {
      setUploadError(errorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="form-body">
        <div className="eyebrow">CSV case import</div>
        <label>
          CSV file
          <input type="file" accept=".csv,text/csv" onChange={(e) => void handleFile(e.target.files?.[0] ?? null)} />
        </label>
        {parseError && <ErrorNote message={parseError} />}
        {headers && (
          <>
            <div className="not-available" style={{ marginBottom: 12 }}>
              <Icon name="file" />
              <span>
                Map each column to a case field, or leave it as a facts key. Any column left as "Keep as a facts key"
                is stored under that exact column name in the case's facts.
              </span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>CSV column</th>
                    <th>Maps to</th>
                  </tr>
                </thead>
                <tbody>
                  {headers.map((h) => (
                    <tr key={h}>
                      <td>
                        <strong>{h}</strong>
                      </td>
                      <td>
                        <select
                          value={mapping[h] ?? "facts"}
                          onChange={(e) => setMapping((m) => ({ ...m, [h]: e.target.value as ColumnMappingTarget }))}
                        >
                          {MAPPING_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {uploadError && <ErrorNote message={uploadError} />}
            <div style={{ marginTop: 12 }}>
              <Button kind="primary" onClick={submit} disabled={uploading}>
                {uploading ? "Uploading…" : "Upload and import"}
              </Button>
            </div>
          </>
        )}
        {result && (
          <div className="rule-stack" style={{ marginTop: 16 }}>
            <div className="status-grid" style={{ marginBottom: 12 }}>
              <div>
                <span>Total rows</span>
                <strong>{result.total_rows}</strong>
              </div>
              <div>
                <span>Imported</span>
                <strong>{result.valid_rows}</strong>
              </div>
              <div>
                <span>Failed</span>
                <strong>{result.invalid_rows}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>
                  <Badge tone={result.status === "completed" ? "success" : result.status === "failed" ? "warning" : "neutral"}>
                    {result.status}
                  </Badge>
                </strong>
              </div>
            </div>
            {result.row_errors && result.row_errors.length > 0 && (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.row_errors.map((e) => (
                      <tr key={e.row_number}>
                        <td>
                          <strong>{e.row_number}</strong>
                        </td>
                        <td>{e.errors.join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {result.invalid_rows === 0 && (
              <div className="success">
                <span>
                  <strong>Every row imported cleanly.</strong>
                </span>
              </div>
            )}
          </div>
        )}
        <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          <Button kind="ghost" onClick={() => setShowPastImports(!showPastImports)}>
            {showPastImports ? "Hide past imports" : "View past imports"}
          </Button>
          {showPastImports && (
            <div className="table-scroll" style={{ marginTop: 10 }}>
              <table>
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Status</th>
                    <th>Valid / Invalid</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {(pastImports.data?.import_jobs ?? []).map((job) => (
                    <tr key={job.id}>
                      <td>
                        <strong>{job.filename}</strong>
                      </td>
                      <td>
                        <Badge tone={job.status === "completed" ? "success" : job.status === "failed" ? "warning" : "neutral"}>
                          {job.status}
                        </Badge>
                      </td>
                      <td>
                        {job.valid_rows} / {job.invalid_rows}
                      </td>
                      <td>{new Date(job.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                  {pastImports.data && pastImports.data.import_jobs.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: "center", color: "var(--muted)" }}>
                        No import jobs yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
