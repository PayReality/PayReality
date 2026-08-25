import { useEffect, useState } from "react";
import { Link } from "react-router";
import { aiPolicyBuilderApi } from "./api";
import type { Upload } from "./types";
import { describeApiError, formatStatus } from "../live/format";
import { AiComingSoonBanner } from "../components/AiComingSoonBanner";
import { NextStepGuidance } from "../help/NextStepGuidance";
import { track } from "../services/analytics";

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
      <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>AI Policy Builder</h1>
      <p style={{ color: "var(--pr-text-muted)", fontSize: 13, marginBottom: 8, maxWidth: 560 }}>
        Upload an enterprise authority document (PDF, Word, Excel, CSV, or plain text). It is analyzed
        into candidate Runtime Policies, each with a confidence score and any fields the model could
        not determine highlighted. Nothing is created until you review and promote a candidate.
      </p>
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
      <table className="w-full text-sm" style={{ color: "var(--pr-text-primary)" }}>
        <thead>
          <tr style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12 }}>
            <th className="pb-2">Filename</th>
            <th className="pb-2">Format</th>
            <th className="pb-2">Status</th>
            <th className="pb-2">Uploaded</th>
          </tr>
        </thead>
        <tbody>
          {uploads?.map((u) => (
            <tr
              key={u.upload_id}
              className="transition-colors"
              style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <td className="py-2">
                <Link to={`/governance/upload/${u.upload_id}`} style={{ color: "var(--pr-authority-blue)" }}>
                  {u.filename}
                </Link>
              </td>
              <td className="py-2 uppercase" style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>{u.format}</td>
              <td className="py-2" style={{ color: STATUS_COLOR[u.status] }}>{formatStatus(u.status)}</td>
              <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>
                {new Date(u.uploaded_at).toLocaleString()}
              </td>
            </tr>
          ))}
          {uploads?.length === 0 && (
            <tr>
              <td colSpan={4} className="py-6 text-center" style={{ color: "var(--pr-text-muted)" }}>
                No uploads yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
