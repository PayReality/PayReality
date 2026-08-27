// Mirrors server/app/schemas/policy_simulation.py. Runtime Policy
// Simulator (Authority Intelligence Program, Phase 4, POLICY_SIMULATOR.md).

export interface SimulationInput {
  principal: string;
  action: string;
  resource: string | null;
  amount: number | null;
  currency: string | null;
  agent_name: string;
  context: Record<string, unknown>;
  // PayReality 1.0 Audit finding G03: the Trusted Enterprise Fact
  // subject this simulation resolves facts against, mirroring the real
  // Intent's own `counterparty` field. Optional -- a policy whose
  // condition references an enterprise_knowledge.* fact still evaluates
  // (fail-closed) without one, but see SimulationResult.warnings.
  counterparty: string | null;
}

export interface ConditionEvaluation {
  field: string;
  operator: string;
  expected_value: unknown;
  actual_value: unknown;
  passed: boolean;
}

export interface RuleEvaluation {
  policy_id: string;
  policy_name: string;
  principal: string;
  action: string;
  effect: string;
  scope_matched: boolean;
  conditions: ConditionEvaluation[];
  matched: boolean;
  summary: string;
}

export interface AuthorityTraceStep {
  label: string;
  detail: string | null;
}

// Never persisted, never signed with the real Evidence key -- a hash
// only, so this can never be mistaken for, or replayed as, real
// Evidence. `preview` is always true.
export interface EvidencePreview {
  decision: string;
  policy_version: number;
  policy_bundle_hash: string;
  principal: string;
  action: string;
  resource: string | null;
  evaluated_at: string;
  receipt_hash: string;
  preview: true;
}

export type SimulationDecision = "ALLOW" | "DENY" | "HUMAN_REVIEW";

export interface SimulationResult {
  decision: SimulationDecision;
  policy_key: string;
  policy_name: string;
  policy_version: number;
  policy_bundle_hash: string;
  generated_at: string;
  review_reason: string | null;
  deny_reason: string | null;
  rules: RuleEvaluation[];
  authority_trace: AuthorityTraceStep[];
  evidence_preview: EvidencePreview;
  // PayReality 1.0 Audit finding G03: the real Trusted Enterprise Facts
  // this simulation actually resolved and evaluated against, {} when
  // none were needed or none resolved.
  facts_evaluated: Record<string, unknown>;
  // A real, visible limitation this simulation could not resolve --
  // e.g. a policy needs an enterprise_knowledge fact but no
  // counterparty was given to look it up against. Never a silent
  // guess: empty whenever nothing was left unresolved.
  warnings: string[];
}

export interface Scenario {
  id: string;
  policy_key: string;
  name: string;
  input: SimulationInput;
  expected_outcome: SimulationDecision;
  created_by: string | null;
  created_at: string;
}

export interface ScenarioRunResult {
  scenario_id: string;
  scenario_name: string;
  expected_outcome: SimulationDecision;
  actual_outcome: SimulationDecision;
  passed: boolean;
  result: SimulationResult;
}

export interface BatchRow {
  row_number: number;
  principal: string;
  action: string;
  decision: SimulationDecision | null;
  error: string | null;
}

export interface BatchSimulationResult {
  total: number;
  allowed: number;
  denied: number;
  escalated: number;
  errors: number;
  sample_rows: BatchRow[];
  sample_truncated: boolean;
  policy_version: number;
  policy_bundle_hash: string;
}
