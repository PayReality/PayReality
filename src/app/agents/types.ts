import type { AgentHealth, AgentStatus, LiveAgent } from "../live/types";

export type { AgentHealth, AgentStatus };

export interface AgentListPage {
  agents: LiveAgent[];
  total: number;
  limit: number;
  offset: number;
}

export interface Certificate {
  id: string;
  agent_id: string;
  status: "issued" | "active" | "rotated" | "expired" | "revoked";
  public_key: string;
  issued_at: string;
  activated_at: string | null;
  rotated_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface LinkedPolicy {
  policy_key: string;
  name: string;
  version: number;
  status: string;
  // Product Experience Remediation Milestone 1: what this policy
  // actually governs -- previously invisible without opening Governance.
  action: string | null;
  resource: string | null;
}

export interface DecisionSummary {
  id: string;
  outcome: "ALLOW" | "DENY" | "HUMAN_REVIEW";
  reason: string | null;
  created_at: string;
  // Product Experience Remediation Milestone 1: closes the previously-
  // disclosed gap. Deliberately no amount/currency -- contextual, not
  // universal.
  action: string | null;
  resource: string | null;
}

export interface EvidenceSummary {
  id: string;
  status: "VERIFIED" | "PENDING" | "REJECTED";
  created_at: string;
}

export interface AuditEvent {
  id: string;
  agent_id: string;
  event_type: string;
  actor: string | null;
  payload: Record<string, unknown>;
  key_id: string;
  signature: string;
  created_at: string;
}

export interface AgentDetail {
  agent: LiveAgent;
  principal_name: string;
  policies: LinkedPolicy[];
  certificates: Certificate[];
  recent_decisions: DecisionSummary[];
  recent_evidence: EvidenceSummary[];
  recent_audit_events: AuditEvent[];
}

export interface BulkActionItemResult {
  agent_id: string;
  ok: boolean;
  error: string | null;
}

export interface BulkActionResult {
  results: BulkActionItemResult[];
  succeeded: number;
  failed: number;
}
