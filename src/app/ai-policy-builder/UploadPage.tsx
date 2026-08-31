import { useEffect, useState } from "react";
import { Link } from "react-router";
import { aiPolicyBuilderApi } from "./api";
import type { Upload } from "./types";
import { describeApiError, formatStatus } from "../live/format";
import { AiComingSoonBanner } from "../components/AiComingSoonBanner";
import { NextStepGuidance } from "../help/NextStepGuidance";
import { track } from "../services/analytics";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { StatusBadge } from "../components/ui/status-badge";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";
import { Sparkles, FileCode2 } from "lucide-react";

const STATUS_COLOR: Record<string, string> = {
  uploaded: "var(--pr-text-muted)",
  extracted: "var(--pr-trust-green)",
  failed: "var(--pr-critical-red)",
};

export function AIPolicyBuilderUploadPage() {
  const [uploads, setUploads] = useState<Upload[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [justUploaded, setJustUploaded] = useState<Upload | null>(null);

  function load() {
    aiPolicyBuilderApi
      .listUploads()
      .then(setUploads)
      .catch((e) => {
        setUploads([]);
        setMessage(describeApiError(e, "Loading past uploads"));
      });
  }

  useEffect(load, []);
  useEffect(() => {
    aiPolicyBuilderApi.getStatus().then((s) => setAiEnabled(s.ai_enabled));
  }, []);

  async function handleUpload(file: File) {
    setUploading(true);
    setMessage(null);
    setJustUploaded(null);
    const startedAt = Date.now();
    try {
      const upload = await aiPolicyBuilderApi.upload(file);
      track("Governance Document Uploaded", { document_count: 1, document_processing_ms: Date.now() - startedAt });
      if (upload.status === "extracted") {
        setJustUploaded(upload);
        load();
      } else {
        setMessage(`Upload failed to extract (status: ${upload.status}). ${upload.error ?? ""}`);
        load();
      }
    } catch (e) {
      setMessage(describeApiError(e, "Upload"));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="AI Policy Builder"
        description="Upload an enterprise authority document (PDF, Word, Excel, CSV, or plain text). It is analyzed into candidate Runtime Policies, each with a confidence score and any fields the model could not determine highlighted."
      />
      <div
        className="flex items-start gap-2 mb-4 px-3 py-2 rounded-lg"
        style={{ backgroundColor: "var(--pr-overlay-05)" }}
      >
        <Sparkles className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-authority-blue)" }} />
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          The AI only interprets and proposes; it does not create organizational authority. Nothing
          becomes a real rule until a human with Governance permission reviews and promotes a candidate.
        </p>
      </div>
      <p style={{ color: "var(--pr-text-disabled)", fontSize: 12, marginBottom: 16, maxWidth: 560 }}>
        For most organisations, start with the{" "}
        <Link to="/governance/authority-builder" style={{ color: "var(--pr-authority-blue)" }}>
          Authority Builder
        </Link>{" "}
        instead: it reconciles multiple documents together and models your organisation's actual
        delegation chains. Use this single-document tool only for a quick one-off extraction.
      </p>

      {!aiEnabled && <AiComingSoonBanner />}

      <label
        className="flex flex-col items-center justify-center gap-2 p-8 rounded-xl border-2 border-dashed cursor-pointer mb-8"
        style={{ borderColor: "rgba(77,124,254,0.25)" }}
      >
        <span className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>
          {uploading ? "Uploading and analyzing..." : "Upload a document (.pdf, .docx, .xlsx, .csv, .txt)"}
        </span>
        <input
          type="file"
          accept=".pdf,.docx,.xlsx,.xls,.csv,.txt"
          className="hidden"
          disabled={uploading}
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
        />
      </label>

      {message && (
        <p role="alert" style={{ color: "var(--pr-warning-amber)", marginBottom: 16 }}>
          {message} <button type="button" onClick={load} style={{ color: "var(--pr-authority-blue)", textDecoration: "underline" }}>Retry</button>
        </p>
      )}

      {justUploaded && (
        <NextStepGuidance
          message={`"${justUploaded.filename}" was analyzed successfully. Review what the AI found before anything becomes a real rule.`}
          actionLabel="Review AI Findings"
          actionPath={`/governance/upload/${justUploaded.upload_id}`}
        />
      )}

      <h2 className="text-sm font-medium mb-3 mt-6" style={{ color: "var(--pr-text-primary)" }}>Past uploads</h2>
      <Table>
        <TableHead>
          <TableRow style={{ borderTop: "none" }}>
            <TableHeaderCell>Filename</TableHeaderCell>
            <TableHeaderCell>Format</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Uploaded</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {uploads?.map((u) => (
            <TableRow
              key={u.upload_id}
              className="transition-colors"
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <TableCell truncate={false}>
                <Link to={`/governance/upload/${u.upload_id}`} style={{ color: "var(--pr-authority-blue)" }}>
                  {u.filename}
                </Link>
              </TableCell>
              <TableCell className="uppercase" style={{ color: "var(--pr-text-muted)", fontSize: 12 }} truncate={false}>{u.format}</TableCell>
              <TableCell truncate={false}><StatusBadge color={STATUS_COLOR[u.status]} label={formatStatus(u.status)} /></TableCell>
              <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                {new Date(u.uploaded_at).toLocaleString()}
              </TableCell>
            </TableRow>
          ))}
          {uploads?.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} truncate={false}>
                <EmptyState icon={FileCode2} title="No uploads yet" description="Upload a document above to see AI-proposed candidate policies here." />
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
