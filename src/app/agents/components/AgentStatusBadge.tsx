import { formatStatus } from "../../live/format";
import { StatusBadge } from "../../components/ui/status-badge";
import type { AgentStatus } from "../types";

// Same left-border-plus-text convention as PolicyStatusBadge, so an
// Agent's lifecycle status reads consistently with a Runtime Policy's.
const STATUS_COLOR: Record<AgentStatus, string> = {
  registered: "var(--pr-text-disabled)",
  active: "var(--pr-trust-green)",
  suspended: "var(--pr-warning-amber)",
  revoked: "var(--pr-critical-red)",
  retired: "var(--pr-text-disabled)",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <StatusBadge color={STATUS_COLOR[status]} label={formatStatus(status)} />;
}
