import { apiClient } from "../live/apiClient";
import type {
  BatchSimulationResult,
  Scenario,
  ScenarioRunResult,
  SimulationInput,
  SimulationResult,
} from "./types";

const BASE = "/v1/policy-simulation";

export const policySimulationApi = {
  simulate: (policyKey: string, input: SimulationInput) =>
    apiClient.post<SimulationResult>(`${BASE}/${policyKey}/simulate`, input),

  createScenario: (
    policyKey: string,
    body: { name: string; input: SimulationInput; expected_outcome: string }
  ) => apiClient.post<Scenario>(`${BASE}/${policyKey}/scenarios`, body),

  listScenarios: (policyKey: string) => apiClient.get<Scenario[]>(`${BASE}/${policyKey}/scenarios`),

  runScenario: (scenarioId: string) =>
    apiClient.post<ScenarioRunResult>(`${BASE}/scenarios/${scenarioId}/run`),

  batchSimulate: (policyKey: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient.post<BatchSimulationResult>(`${BASE}/${policyKey}/batch`, form);
  },
};
