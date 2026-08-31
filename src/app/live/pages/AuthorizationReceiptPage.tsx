import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { ShieldCheck, ShieldX, RefreshCw } from "lucide-react";
import { decisionsApi } from "../decisionsApi";
import { integrationsApi } from "../../integrations/api";
import { humanizeAction } from "../../integrations/helpers";
import { describeApiError, formatStatus } from "../format";
import { ContextRow, OUTCOME_STYLE, describeFreshnessStatus, describeSource } from "../components/decisionDisplay";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import type { AuthorizationReceipt } from "../types";

// Issue #4 (Authorization Receipts): the stable, named artifact an
// auditor/customer inspects, distinct from both of its neighbours.
// Evidence (LiveEvidence.tsx) is the cryptographic proof layer -- raw
// signed records. Decision Detail is the causal explanation layer --
// why this outcome, per-condition. This page is the assembled document
// that packages both, plus Historical Policy Binding, Trusted
// Enterprise Facts, human review, and Capability Authorization state
// (where each applies), into one auditor-facing view -- nothing here is
// a second source of truth; every field is a read of a record shown
// elsewhere too.
//
// A capability token is NOT this receipt. A capability is forward-
// looking, ALLOW-only, short-lived, single-use -- a permission slip a
// downstream system may check before executing. This receipt is
// backward-looking, permanent, and re-verifiable regardless of outcome
// -- proof a decision was made, and what governed it. Where a
// capability was issued for this decision, its consumption is shown as
// exactly that -- a recorded fact, never proof the downstream action
// actually executed (see the Capability card below).
export function AuthorizationReceiptPage() {
  const { decisionId } = useParams();
  const [receipt, setReceipt] = useState<AuthorizationReceipt | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  // Trusted Integration Architecture, Phase 4 (section 29): resolved
  // only when this receipt actually carries integration provenance.
  const [systemName, setSystemName] = useState<string | null>(null);
  const [trustedConnectionName, setTrustedConnectionName] = useState<string | null>(null);
  const [mappingLabel, setMappingLabel] = useState<string | null>(null);

  function load() {
    if (!decisionId) return;
    setLoading(true);
    setLoadError(null);
    decisionsApi
      .getReceipt(decisionId)
      .then(setReceipt)
      .catch((e) => setLoadError(describeApiError(e, "Loading this receipt")))
      .finally(() => setLoading(false));
  }

  useEffect(load, [decisionId]);

  useEffect(() => {
    const integration = receipt?.integration;
    if (!integration) {
      setSystemName(null);
      setTrustedConnectionName(null);
      setMappingLabel(null);
      return;
    }
    if (integration.integration_id) {
      integrationsApi.getSystem(integration.integration_id).then((s) => setSystemName(s.external_system_label)).catch(() => setSystemName(null));
    }
    if (integration.integration_identity_id) {
      integrationsApi.getTrustedConnection(integration.integration_identity_id).then((t) => setTrustedConnectionName(t.name)).catch(() => setTrustedConnectionName(null));
    }
    if (integration.integration_id && integration.integration_contract_version_id) {
      integrationsApi.getMapping(integration.integration_id, integration.integration_contract_version_id)
        .then((m) => setMappingLabel(`${m.source_operation} → ${humanizeAction(m.canonical_action)}`))
        .catch(() => setMappingLabel(null));
    }
  }, [receipt?.integration]);

  if (loadError) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        {decisionId && (
          <Link to={`/decisions/${decisionId}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to decision</Link>
        )}
        <Alert severity="error" className="text-sm mt-4">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!receipt) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <Skeleton height={16} width={140} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="60%" style={{ marginBottom: 12 }} />
        <Skeleton height={120} style={{ marginBottom: 16 }} />
        <Skeleton height={160} />
      </div>
    );
  }

  const style = OUTCOME_STYLE[receipt.decision.outcome];

  return (
    <div className="p-8 max-w-3xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="flex items-center justify-between gap-3 mb-4">
        <Link to={`/decisions/${receipt.decision.decision_id}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to decision</Link>
        <span style={{ fontSize: 11, color: "var(--pr-text-disabled)", fontFamily: "monospace" }}>{receipt.receipt_id}</span>
      </div>

      <Card padding={24} className="mb-4 pr-enter">
        <p className="text-xs font-semibold uppercase tracking-widest mb-1" style={{ color: "var(--pr-text-muted)" }}>
          Authorization Receipt
        </p>
        <div className="flex items-center gap-3 mb-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: style.bg }}>
            <style.icon className="w-5 h-5" style={{ color: style.fg }} />
          </div>
          <div>
            <p className="font-semibold text-lg" style={{ color: style.fg }}>{formatStatus(receipt.decision.outcome)}</p>
            <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>
              {new Date(receipt.decision.created_at).toLocaleString()} &middot; Source: {describeSource(receipt.decision.source)}
            </p>
          </div>
        </div>
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          {receipt.actor.agent_name ?? "An agent"} requested <strong>{formatStatus(receipt.request.action)}</strong>
          {receipt.request.resource ? <> on <strong>{receipt.request.resource}</strong></> : null}
          {receipt.actor.principal_name ? <>, acting for <strong>{receipt.actor.principal_name}</strong></> : null}
          {receipt.request.amount !== null ? <> ({receipt.request.amount.toLocaleString()} {receipt.request.currency ?? ""})</> : null}.
        </p>
        {receipt.request.correlation_id && (
          <p className="text-xs mt-1" style={{ color: "var(--pr-text-disabled)" }}>
            Correlation ID: <span style={{ fontFamily: "monospace" }}>{receipt.request.correlation_id}</span>
          </p>
        )}

        <div
          className="flex items-center gap-2 mt-4 pt-4"
          style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
          role="status"
        >
          {receipt.verification.signature_valid ? (
            <ShieldCheck className="w-4 h-4 flex-shrink-0" style={{ color: "var(--pr-trust-green)" }} />
          ) : (
            <ShieldX className="w-4 h-4 flex-shrink-0" style={{ color: "var(--pr-critical-red)" }} />
          )}
          <p className="text-sm" style={{ color: receipt.verification.signature_valid ? "var(--pr-trust-green)" : "var(--pr-critical-red)" }}>
            {receipt.verification.signature_valid
              ? "Signature verified -- this record has not been altered."
              : "Signature verification failed -- this record may have been altered."}
          </p>
          <button
            onClick={load}
            disabled={loading}
            className="ml-auto flex items-center gap-1 text-xs disabled:opacity-40"
            style={{ color: "var(--pr-authority-blue)" }}
          >
            <RefreshCw className="w-3 h-3" /> {loading ? "Checking..." : "Re-check"}
          </button>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4 pr-enter">
        <Card padding={20}>
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Governing authority</p>
          <ContextRow label="Policy bundle version" value={receipt.authority.bundle_version !== null ? String(receipt.authority.bundle_version) : "Not recorded"} muted={receipt.authority.bundle_version === null} />
          <ContextRow label="Bundle hash" value={receipt.authority.bundle_hash ? `${receipt.authority.bundle_hash.slice(0, 16)}...` : "Not recorded"} muted={!receipt.authority.bundle_hash} />
          <ContextRow label="Activated" value={receipt.authority.activated_at ? new Date(receipt.authority.activated_at).toLocaleDateString() : "Not recorded"} muted={!receipt.authority.activated_at} />
          <ContextRow label="Retired" value={receipt.authority.retired_at ? new Date(receipt.authority.retired_at).toLocaleDateString() : "Still active, or never retired"} muted={!receipt.authority.retired_at} />
          <p className="text-[11px] mt-3 pt-3" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
            This is the exact bundle that governed this decision, not whatever policy is active today -- it stays
            correct even after the organisation has since deployed newer versions.
          </p>
        </Card>

        <Card padding={20}>
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Trusted enterprise facts</p>
          {receipt.facts.length > 0 ? (
            receipt.facts.map((f, i) => (
              <ContextRow key={`${f.key}-${i}`} label={f.key} value={String(f.value)} />
            ))
          ) : (
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No external facts were evaluated for this decision.</p>
          )}
        </Card>
      </div>

      {receipt.integration && (
        <div className="mb-4 pr-enter">
          <Card padding={20} data-tour="receipt-integration-provenance">
            <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Reported through a trusted connection</p>
            <ContextRow label="Reported through" value={trustedConnectionName ? `${trustedConnectionName} trusted connection` : "Loading..."} muted={!trustedConnectionName} />
            <ContextRow label="System" value={systemName ?? "Loading..."} muted={!systemName} />
            <ContextRow label="Mapping" value={mappingLabel ?? "Loading..."} muted={!mappingLabel} />
            <ContextRow label="Environment" value={receipt.integration.environment ? formatStatus(receipt.integration.environment) : "Not recorded"} muted={!receipt.integration.environment} />
            <ContextRow label="External operation" value={receipt.integration.external_operation_id ?? "Not recorded"} muted={!receipt.integration.external_operation_id} />
            <p className="text-[11px] mt-2 pt-2" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
              An authenticated trusted connection attested it observed this operation -- this is not proof
              the external system actually executed it.
            </p>
          </Card>
        </div>
      )}

      {receipt.human_review && (
        <div className="mb-4 pr-enter">
          <Card padding={20}>
            <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Human review</p>
            <p className="text-sm" style={{ color: "var(--pr-text-primary)" }}>
              Resolved <strong>{receipt.human_review.resolution}</strong> by {receipt.human_review.resolved_by}
              {receipt.human_review.reason ? ` -- ${receipt.human_review.reason}` : ""}
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--pr-text-disabled)" }}>
              {new Date(receipt.human_review.resolved_at).toLocaleString()}
            </p>
          </Card>
        </div>
      )}

      {receipt.capability && (
        <div className="mb-4 pr-enter">
          <Card padding={20}>
            <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Capability authorization</p>
            <ContextRow label="Audience" value={receipt.capability.audience ?? "Not set"} muted={!receipt.capability.audience} />
            <ContextRow label="Expires" value={receipt.capability.expires_at ? new Date(receipt.capability.expires_at).toLocaleString() : "Not set"} />
            <ContextRow
              label="Consumed"
              value={receipt.capability.consumed_at ? new Date(receipt.capability.consumed_at).toLocaleString() : "Not yet"}
              muted={!receipt.capability.consumed_at}
            />
            <p className="text-[11px] mt-2 pt-2" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
              Consumption means a downstream system redeemed this token -- it is not confirmation that the
              downstream action actually completed.
            </p>
          </Card>
        </div>
      )}

      <div className="mb-4 pr-enter">
        <Card padding={20}>
          <button
            onClick={() => setShowTechnical((v) => !v)}
            className="w-full flex items-center justify-between gap-3 text-left"
            aria-expanded={showTechnical}
          >
            <p className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Technical verification details</p>
            <span className="text-xs font-medium flex-shrink-0" style={{ color: "var(--pr-authority-blue)" }}>
              {showTechnical ? "Hide" : "Show"}
            </span>
          </button>
          {showTechnical && (
            <div className="mt-3 pt-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
              <ContextRow label="Evidence ID" value={receipt.evidence.evidence_id} />
              <ContextRow label="Signing key ID" value={receipt.evidence.key_id} />
              <ContextRow label="Algorithm" value={receipt.verification.algorithm} />
              <ContextRow label="Signature" value={`${receipt.evidence.signature.slice(0, 32)}...`} />
              <ContextRow label="Record hash" value={`${receipt.evidence.payload_hash.slice(0, 32)}...`} />
              <ContextRow label="Prior record's hash" value={receipt.evidence.previous_hash ? `${receipt.evidence.previous_hash.slice(0, 32)}...` : "None (first record in this chain)"} />
              <ContextRow label="Evidence status" value={receipt.evidence.status} />
              {receipt.authority.policies.length > 0 && (
                <>
                  <p className="text-xs mt-3 mb-1" style={{ color: "var(--pr-text-muted)" }}>Policies in this bundle</p>
                  {receipt.authority.policies.map((p) => (
                    <ContextRow key={p.id} label={p.name} value={`v${p.version}, ${p.effect}`} />
                  ))}
                </>
              )}
              <p className="text-[11px] mt-3 pt-3" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
                Generated {new Date(receipt.generated_at).toLocaleString()}. Verification is recomputed on every
                request, never cached -- open the full Evidence record for the complete signed payload.
              </p>
            </div>
          )}
        </Card>
      </div>

      <Link to="/evidence" className="text-xs" style={{ color: "var(--pr-authority-blue)" }}>
        Open the full Evidence Portal &rarr;
      </Link>
    </div>
  );
}
