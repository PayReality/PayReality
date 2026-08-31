import { useId, useEffect, useState } from "react";
import { Link } from "react-router";
import { aiAuthorityBuilderApi } from "./api";
import type { Corpus } from "./types";
import { describeApiError, formatStatus } from "../live/format";
import { AiComingSoonBanner } from "../components/AiComingSoonBanner";
import { NextStepGuidance } from "../help/NextStepGuidance";
import { track, trackError } from "../services/analytics";
import { FieldLabel } from "../components/ui/label";
import { Button } from "../components/ui/button";
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

export function AIAuthorityBuilderUploadPage() {
  const formId = useId();
  const [corpora, setCorpora] = useState<Corpus[] | null>(null);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [justCreated, setJustCreated] = useState<Corpus | null>(null);

  function load() {
    aiAuthorityBuilderApi
      .listCorpora()
      .then(setCorpora)
      .catch((e) => {
        setCorpora([]);
        setMessage(describeApiError(e, "Loading past corpora"));
      });
  }

  useEffect(load, []);
  useEffect(() => {
    aiAuthorityBuilderApi.getStatus().then((s) => setAiEnabled(s.ai_enabled));
  }, []);

  function addFiles(newFiles: FileList | null) {
    if (!newFiles) return;
    setFiles((prev) => [...prev, ...Array.from(newFiles)]);
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit() {
    if (files.length === 0) {
      setMessage("Select at least one document.");
      return;
    }
    setUploading(true);
    setMessage(null);
    setJustCreated(null);
    const startedAt = Date.now();
    try {
      const corpus = await aiAuthorityBuilderApi.createCorpus(name.trim() || "Untitled corpus", files);
      const documentProcessingMs = Date.now() - startedAt;
      track("Governance Document Uploaded", { document_count: files.length, document_processing_ms: documentProcessingMs });
      if (corpus.status === "extracted") {
        track("Authority Graph Generated", { corpus_id: corpus.corpus_id, authority_graph_generation_ms: documentProcessingMs });
        setJustCreated(corpus);
        setFiles([]);
        setName("");
        load();
      } else {
        setMessage(`Corpus failed to extract (status: ${corpus.status}). ${corpus.error ?? ""}`);
        trackError("Authority Graph Generation Failed", {
          error_type: "extraction_failed",
          component: "ai_authority_builder",
          duration_ms: documentProcessingMs,
        });
        load();
      }
    } catch (e) {
      setMessage(describeApiError(e, "Upload"));
      trackError("Authority Graph Generation Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "ai_authority_builder",
        duration_ms: Date.now() - startedAt,
      });
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="AI Authority Builder"
        description="Upload one or many governance documents together (delegation of authority, approval matrix, procurement policy, HR policy, risk policy, security policy, standard operating procedures, or similar). They are analyzed as a single Authority Corpus, never document by document, so a limit stated in one file and contradicted in another is reported as a conflict, not silently dropped."
      />
      <div
        className="flex items-start gap-2 mb-4 px-3 py-2 rounded-lg"
        style={{ backgroundColor: "var(--pr-overlay-05)" }}
      >
        <Sparkles className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-authority-blue)" }} />
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          The AI only interprets and proposes; it does not create organizational authority. Nothing
          becomes a real rule until a human with Governance permission reviews and promotes a finding.
        </p>
      </div>

      {!aiEnabled && <AiComingSoonBanner />}

      <div
        style={{
          backgroundColor: "var(--pr-bg-card)",
          border: "1px solid var(--pr-overlay-05)",
          borderRadius: 12,
          padding: 20,
          marginBottom: 24,
        }}
      >
        <FieldLabel htmlFor={`${formId}-name`}>
          Corpus name
        </FieldLabel>
        <input
          id={`${formId}-name`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. 2026 Delegation of Authority Refresh"
          style={{
            backgroundColor: "var(--pr-bg-hover)",
            border: "1px solid var(--pr-overlay-10)",
            color: "var(--pr-text-primary)",
            borderRadius: 6,
            padding: "6px 8px",
            fontSize: 13,
            width: "100%",
            marginBottom: 16,
          }}
        />

        <label
          className="flex flex-col items-center justify-center gap-2 p-6 rounded-xl border-2 border-dashed cursor-pointer mb-3"
          style={{ borderColor: "rgba(77,124,254,0.25)" }}
        >
          <span className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>
            Add documents (.pdf, .docx, .xlsx, .csv, .txt)
          </span>
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.xls,.csv,.txt"
            className="hidden"
            onChange={(e) => addFiles(e.target.files)}
          />
        </label>

        {files.length > 0 && (
          <div className="mb-4">
            {files.map((f, i) => (
              <div key={i} className="flex items-center justify-between gap-3 py-1" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>
                <span style={{ wordBreak: "break-word" }}>{f.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  aria-label={`Remove ${f.name}`}
                  style={{ color: "var(--pr-critical-red)", fontSize: 12, padding: "4px 8px", flexShrink: 0 }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <Button variant="primary" onClick={handleSubmit} disabled={uploading}>
          {uploading ? "Uploading and analyzing corpus..." : `Analyze corpus (${files.length} file(s))`}
        </Button>

        {message && (
          <p role="alert" style={{ color: "var(--pr-warning-amber)", marginTop: 12 }}>
            {message} <button type="button" onClick={load} style={{ color: "var(--pr-authority-blue)", textDecoration: "underline" }}>Retry</button>
          </p>
        )}
      </div>

      {justCreated && (
        <NextStepGuidance
          message={`"${justCreated.name}" was analyzed successfully. Review what the AI found before anything becomes a real rule.`}
          actionLabel="Review AI Findings"
          actionPath={`/governance/authority-builder/${justCreated.corpus_id}`}
        />
      )}

      <h2 className="text-sm font-medium mb-3 mt-6" style={{ color: "var(--pr-text-primary)" }}>Past corpora</h2>
      <Table>
        <TableHead>
          <TableRow style={{ borderTop: "none" }}>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Documents</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Uploaded</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {corpora?.map((c) => (
            <TableRow
              key={c.corpus_id}
              className="transition-colors"
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <TableCell truncate={false}>
                <Link to={`/governance/authority-builder/${c.corpus_id}`} style={{ color: "var(--pr-authority-blue)" }}>
                  {c.name}
                </Link>
              </TableCell>
              <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>{c.document_count}</TableCell>
              <TableCell truncate={false}><StatusBadge color={STATUS_COLOR[c.status]} label={formatStatus(c.status)} /></TableCell>
              <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                {new Date(c.created_at).toLocaleString()}
              </TableCell>
            </TableRow>
          ))}
          {corpora?.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} truncate={false}>
                <EmptyState icon={FileCode2} title="No corpora yet" description="Upload one or more documents above to build your first Authority Corpus." />
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
