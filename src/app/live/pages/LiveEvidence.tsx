import { useEffect, useState } from "react";
import { CheckCircle2, Database, KeyRound, Link2, ShieldCheck, ShieldX } from "lucide-react";
import { apiClient } from "../apiClient";
import { describeApiError, formatStatus } from "../format";
import { HelpIcon } from "../../help/HelpIcon";
import { trackError } from "../../services/analytics";
import { useResourceSync } from "../../services/resourceSync";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { SkeletonRows } from "../../components/ui/skeleton";
import { DEMO_MODE } from "../../demo/config";
import { useNow, formatRelativeTime } from "../../demo/liveClock";
import type {
  ChainVerificationResponse,
  EvidencePayload,
  LiveEvidence as LiveEvidenceType,
  VerificationKeyHistoryResponse,
} from "../types";

const FIELD_LABEL: Record<string, string> = {
  action: "Action",
  amount: "Amount",
  authority_outcome: "Authority outcome",
  risk_classification: "Risk level",
};

const SUMMARY_FIELDS: (keyof EvidencePayload)[] = ["action", "amount", "authority_outcome", "risk_classification"];
const PAGE_SIZE = 10;

export function LiveEvidence() {
  const now = useNow();
  const [records, setRecords] = useState<LiveEvidenceType[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [verifyResults, setVerifyResults] = useState<Record<string, boolean>>({});
  const [verifyErrors, setVerifyErrors] = useState<Record<string, string>>({});
  const [verifying, setVerifying] = useState<Set<string>>(new Set());
  const [expandedDetails, setExpandedDetails] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [keyHistory, setKeyHistory] = useState<VerificationKeyHistoryResponse | null>(null);
  const [keyHistoryError, setKeyHistoryError] = useState<string | null>(null);
  const [chainResult, setChainResult] = useState<ChainVerificationResponse | null>(null);
  const [chainChecking, setChainChecking] = useState(false);
  const [chainError, setChainError] = useState<string | null>(null);

  function load() {
    setLoadError(null);
    // Evidence generation itself has no separate client-triggered step to
    // instrument (it's an automatic server-side side effect of decision
    // evaluation) -- a failure to load the Evidence list here is the
    // closest available signal for "Evidence Generation Failed" from the
    // frontend, so that's what a failure on this fetch is attributed to.
    // This request had no .catch() at all before this change.
    apiClient.get<LiveEvidenceType[]>("/v1/evidence").then(setRecords).catch((e) => {
      setLoadError(describeApiError(e, "Evidence"));
      trackError("Evidence Generation Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "evidence_list_fetch",
      });
    });
  }

  function loadKeyHistory() {
    setKeyHistoryError(null);
    apiClient
      .get<VerificationKeyHistoryResponse>("/v1/evidence/verification-keys")
      .then(setKeyHistory)
      .catch((e) => setKeyHistoryError(describeApiError(e, "Signing key history")));
  }

  useEffect(load, []);
  useEffect(loadKeyHistory, []);
  // Milestone 13 Phase 6A: catches a decision/resolution created from
  // another tab (or this tab's own Decision Center flow, just via the
  // cross-tab path in case the two are open side by side), or this tab
  // having been left open and revisited.
  useResourceSync(["decisions", "evidence"], load);

  const verify = async (id: string) => {
    setVerifying((prev) => new Set(prev).add(id));
    setVerifyErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const result = await apiClient.post<{ valid: boolean }>(`/v1/evidence/${id}/verify`);
      setVerifyResults((prev) => ({ ...prev, [id]: result.valid }));
    } catch (e) {
      setVerifyErrors((prev) => ({ ...prev, [id]: describeApiError(e, "Verify signature") }));
    } finally {
      setVerifying((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const checkChainIntegrity = async () => {
    setChainChecking(true);
    setChainError(null);
    try {
      const result = await apiClient.get<ChainVerificationResponse>("/v1/evidence/chain/verify");
      setChainResult(result);
    } catch (e) {
      setChainError(describeApiError(e, "Chain integrity check"));
    } finally {
      setChainChecking(false);
    }
  };

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Database className="w-5 h-5" style={{ color: "var(--pr-authority-blue)" }} />
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--pr-authority-blue)" }}>
            Evidence Vault
          </span>
        </div>
        <div className="flex items-center gap-1.5 mb-2">
          <h1 style={{ color: "var(--pr-text-primary)" }}>Evidence</h1>
          <HelpIcon articleId="evidence" />
        </div>
        <p style={{ color: "var(--pr-text-muted)" }}>
          Every decision produces a cryptographically signed, unchangeable record of which of your
          organisation's rules allowed it, not just what happened. Verify a signature to detect
          any tampering.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 mb-8">
        <Card padding={20} borderColor="var(--pr-overlay-06)">
          <div className="flex items-center gap-2 mb-3">
            <KeyRound className="w-4 h-4" style={{ color: "var(--pr-verification-purple)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>
              Signing key history
            </h2>
          </div>
          {keyHistoryError && (
            <Alert severity="warning" className="text-xs">
              <div className="flex items-center gap-3">
                <span>{keyHistoryError}</span>
                <Button variant="ghost" size="sm" onClick={loadKeyHistory}>Retry</Button>
              </div>
            </Alert>
          )}
          {!keyHistory && !keyHistoryError && <SkeletonRows count={2} height={36} />}
          {keyHistory && (
            <div className="space-y-2">
              {keyHistory.keys.map((k) => (
                <div key={k.key_id} className="flex items-center justify-between gap-3 text-xs">
                  <div className="min-w-0">
                    <p className="font-mono truncate" style={{ color: "var(--pr-text-primary)" }}>{k.key_id}</p>
                    <p style={{ color: "var(--pr-text-muted)" }}>
                      {k.algorithm} &middot; issued {new Date(k.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <span
                    className="px-2 py-0.5 rounded-full font-medium flex-shrink-0"
                    style={{
                      backgroundColor: k.active ? "rgba(34,197,94,0.1)" : "var(--pr-overlay-06)",
                      color: k.active ? "var(--pr-trust-green)" : "var(--pr-text-muted)",
                    }}
                  >
                    {k.active ? "Active" : k.retired_at ? `Retired ${new Date(k.retired_at).toLocaleDateString()}` : "Retired"}
                  </span>
                </div>
              ))}
              {keyHistory.keys.length === 0 && (
                <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No signing keys recorded yet.</p>
              )}
            </div>
          )}
          <p className="text-xs mt-3" style={{ color: "var(--pr-text-disabled)" }}>
            A record signed under a retired key is still independently verifiable: its key stays
            published here, offline, indefinitely.
          </p>
        </Card>

        <Card padding={20} borderColor="var(--pr-overlay-06)">
          <div className="flex items-center gap-2 mb-3">
            <Link2 className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>
              Chain integrity check
            </h2>
          </div>
          <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
            Checks every record's signature and confirms none has been deleted or reordered, not
            just that individual signatures are valid.
          </p>
          <Button variant="ghost" size="sm" onClick={checkChainIntegrity} disabled={chainChecking}>
            {chainChecking ? "Checking…" : "Run chain integrity check"}
          </Button>
          {chainError && (
            <Alert severity="warning" className="text-xs mt-3">
              <div className="flex items-center gap-3">
                <span>{chainError}</span>
              </div>
            </Alert>
          )}
          {chainResult && (
            <div
              className="mt-3 p-3 text-xs"
              style={{
                borderLeft: `3px solid ${chainResult.intact ? "var(--pr-trust-green)" : "var(--pr-critical-red)"}`,
                backgroundColor: "var(--pr-overlay-04)",
                borderRadius: 6,
              }}
            >
              <p
                className="font-medium mb-1 flex items-center gap-1.5"
                style={{ color: chainResult.intact ? "var(--pr-trust-green)" : "var(--pr-critical-red)" }}
              >
                {chainResult.intact ? <ShieldCheck className="w-3.5 h-3.5" /> : <ShieldX className="w-3.5 h-3.5" />}
                {chainResult.intact ? "Chain intact" : "Chain integrity issue found"}
              </p>
              <p style={{ color: "var(--pr-text-muted)" }}>{chainResult.total} records checked.</p>
              {chainResult.invalid_signatures.length > 0 && (
                <p style={{ color: "var(--pr-critical-red)" }}>
                  {chainResult.invalid_signatures.length} invalid signature
                  {chainResult.invalid_signatures.length > 1 ? "s" : ""}.
                </p>
              )}
              {chainResult.broken_links.length > 0 && (
                <p style={{ color: "var(--pr-critical-red)" }}>
                  {chainResult.broken_links.length} broken chain link
                  {chainResult.broken_links.length > 1 ? "s" : ""}.
                </p>
              )}
            </div>
          )}
        </Card>
      </div>

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!records && !loadError && <SkeletonRows count={4} height={90} />}

      <div className="space-y-3">
        {records?.length === 0 && (
          <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>
            No evidence yet. Go to Decisions and test one.
          </p>
        )}
        {records?.slice(0, visibleCount).map((e) => {
          const verified = verifyResults[e.evidence_id];
          return (
            <Card key={e.evidence_id} padding={20} data-tour={e === records?.[0] ? "evidence-record" : undefined}>
              <div className="flex items-start justify-between mb-3">
                <div>
                  <p className="text-sm font-mono" style={{ color: "var(--pr-authority-blue)" }}>{e.evidence_id}</p>
                  <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                    {DEMO_MODE ? formatRelativeTime(e.created_at, now) : new Date(e.created_at).toLocaleString()}
                  </p>
                </div>
                <span
                  className="text-xs px-2.5 py-1 rounded-full font-medium"
                  style={{
                    backgroundColor: e.status === "VERIFIED" ? "rgba(34,197,94,0.1)" : e.status === "REJECTED" ? "rgba(239,68,68,0.1)" : "rgba(245,158,11,0.1)",
                    color: e.status === "VERIFIED" ? "var(--pr-trust-green)" : e.status === "REJECTED" ? "var(--pr-critical-red)" : "var(--pr-warning-amber)",
                  }}
                >
                  {formatStatus(e.status)}
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-xs">
                {SUMMARY_FIELDS.map((k) => (
                  <div key={k}>
                    <p style={{ color: "var(--pr-text-muted)" }}>{FIELD_LABEL[k] ?? k}</p>
                    <p style={{ color: "var(--pr-text-primary)" }}>{String(e.payload[k] ?? "N/A")}</p>
                  </div>
                ))}
              </div>

              {(e.payload.principal_id || e.payload.authority_context || e.payload.enterprise_system_name) && (
                <div
                  className="mb-4 p-3 text-xs"
                  style={{ borderLeft: "3px solid var(--pr-authority-blue)", backgroundColor: "var(--pr-overlay-04)", borderRadius: 6 }}
                >
                  <p className="font-medium mb-1.5" style={{ color: "var(--pr-authority-blue)" }}>
                    Authorization
                  </p>
                  {e.payload.principal_id && (
                    <p className="mb-1" style={{ color: "var(--pr-text-muted)" }}>
                      Acting principal:{" "}
                      <span style={{ color: "var(--pr-text-primary)", fontFamily: "monospace" }}>
                        {e.payload.principal_id}
                      </span>
                    </p>
                  )}
                  {e.payload.authority_context &&
                    [
                      e.payload.authority_context.role,
                      e.payload.authority_context.team,
                      e.payload.authority_context.department,
                      e.payload.authority_context.business_unit,
                      e.payload.authority_context.organization,
                    ].some(Boolean) && (
                      <p className="mb-1" style={{ color: "var(--pr-text-muted)" }}>
                        {[
                          e.payload.authority_context.role,
                          e.payload.authority_context.team,
                          e.payload.authority_context.department,
                          e.payload.authority_context.business_unit,
                          e.payload.authority_context.organization,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                  {e.payload.delegation_chain && e.payload.delegation_chain.length > 0 && (
                    <p className="mb-1" style={{ color: "var(--pr-text-muted)" }}>
                      Delegated via {e.payload.delegation_chain.length} active relationship
                      {e.payload.delegation_chain.length > 1 ? "s" : ""}
                    </p>
                  )}
                  {(!!e.payload.authority_ids?.length || !!e.payload.evaluated_mandate_ids?.length) && (
                    <p className="mb-1 font-mono" style={{ color: "var(--pr-text-disabled)" }}>
                      {e.payload.authority_ids?.length ? `Authority: ${e.payload.authority_ids.join(", ")}` : null}
                      {e.payload.authority_ids?.length && e.payload.evaluated_mandate_ids?.length ? " · " : null}
                      {e.payload.evaluated_mandate_ids?.length
                        ? `Mandate: ${e.payload.evaluated_mandate_ids.join(", ")}`
                        : null}
                    </p>
                  )}
                  {e.payload.enterprise_system_name && (
                    <p style={{ color: "var(--pr-text-muted)" }}>
                      Enterprise System:{" "}
                      <span style={{ color: "var(--pr-text-primary)" }}>{e.payload.enterprise_system_name}</span>
                    </p>
                  )}
                </div>
              )}

              <div className="flex items-center gap-3 mb-2">
                <button
                  onClick={() => verify(e.evidence_id)}
                  disabled={verifying.has(e.evidence_id)}
                  data-tour={e === records?.[0] ? "verify-signature" : undefined}
                  className="px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5 border transition-all disabled:opacity-60"
                  style={{ borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-secondary)" }}
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> {verifying.has(e.evidence_id) ? "Verifying..." : "Verify signature"}
                </button>
                {verified === true && (
                  <span className="text-xs flex items-center gap-1" style={{ color: "var(--pr-trust-green)" }}>
                    <ShieldCheck className="w-3.5 h-3.5" /> Signature valid
                  </span>
                )}
                {verified === false && (
                  <span className="text-xs flex items-center gap-1" style={{ color: "var(--pr-critical-red)" }}>
                    <ShieldX className="w-3.5 h-3.5" /> Tampered or corrupted
                  </span>
                )}
                {verifyErrors[e.evidence_id] && (
                  <span className="text-xs flex items-center gap-1" style={{ color: "var(--pr-warning-amber)" }}>
                    {verifyErrors[e.evidence_id]}
                  </span>
                )}
                <button
                  onClick={() =>
                    setExpandedDetails((prev) => {
                      const next = new Set(prev);
                      if (next.has(e.evidence_id)) next.delete(e.evidence_id);
                      else next.add(e.evidence_id);
                      return next;
                    })
                  }
                  className="text-xs ml-auto"
                  style={{ color: "var(--pr-text-disabled)" }}
                >
                  {expandedDetails.has(e.evidence_id) ? "Hide" : "Show"} cryptographic details
                </button>
              </div>
              {expandedDetails.has(e.evidence_id) && (
                <p className="text-xs font-mono" style={{ color: "var(--pr-text-disabled)" }}>
                  Signing key: {e.key_id}
                </p>
              )}
            </Card>
          );
        })}
      </div>

      {records && visibleCount < records.length && (
        <div className="flex justify-center mt-4">
          <Button variant="ghost" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
            Show more ({records.length - visibleCount} remaining)
          </Button>
        </div>
      )}
    </div>
  );
}
