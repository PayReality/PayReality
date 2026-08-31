import { formatStatus } from "../../live/format";
import { StatusBadge } from "../../components/ui/status-badge";
import type { ConnectionStatus, MappingStatus, TrustedConnectionStatus } from "../types";

// Trusted Integration Architecture, Phase 4 (section 31): three
// distinct, separately-labeled status vocabularies -- a mapping being
// "Approved" is not the same fact as a connection being "Active,"
// which is not the same fact as a trusted connection being "Active."
// Never conflated into one generic "Active" pill, following
// AgentStatusBadge's own left-border-plus-text convention exactly.

const MAPPING_STATUS_COLOR: Record<MappingStatus, string> = {
  draft: "var(--pr-text-disabled)",
  validated: "var(--pr-authority-blue)",
  approved: "var(--pr-trust-green)",
  retired: "var(--pr-text-disabled)",
};

export function MappingStatusBadge({ status }: { status: MappingStatus }) {
  return <StatusBadge color={MAPPING_STATUS_COLOR[status]} label={formatStatus(status)} />;
}

const CONNECTION_STATUS_COLOR: Record<ConnectionStatus, string> = {
  draft: "var(--pr-text-disabled)",
  active: "var(--pr-trust-green)",
  retired: "var(--pr-text-disabled)",
};

export function ConnectionStatusBadge({ status }: { status: ConnectionStatus }) {
  return <StatusBadge color={CONNECTION_STATUS_COLOR[status]} label={formatStatus(status)} />;
}

const TRUSTED_CONNECTION_STATUS_COLOR: Record<TrustedConnectionStatus, string> = {
  registered: "var(--pr-text-disabled)",
  active: "var(--pr-trust-green)",
  suspended: "var(--pr-warning-amber)",
  revoked: "var(--pr-critical-red)",
  retired: "var(--pr-text-disabled)",
};

export function TrustedConnectionStatusBadge({ status }: { status: TrustedConnectionStatus }) {
  return <StatusBadge color={TRUSTED_CONNECTION_STATUS_COLOR[status]} label={formatStatus(status)} />;
}
