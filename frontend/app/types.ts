export type Band = "allow" | "step_up" | "verify";
export type Direction = "suspicious" | "neutral" | "reassuring" | "unknown";
export type CheckResult = "consistent" | "inconsistent" | "cannot_verify";

export type Signal = {
  id: string;
  category: string;
  finding: string;
  direction: Direction;
  strength: number;
  confidence: number;
  evidence: string;
  spans: [number, number][];
};

export type Check = { id: string; label: string; result: CheckResult; detail: string };

export type Reasoning = {
  status: "used" | "unavailable" | "failed";
  model: string | null;
  provider: string | null;
  local: boolean;
  note: string;
  summary: string;
  concern: "low" | "medium" | "high" | null;
  claimed_identity: string | null;
  request_type: string | null;
  inconsistencies: string[];
  innocent_explanations: string[];
  unknowns: string[];
};

export type Config = { reasoning_enabled: boolean; provider: "gemini" | "anthropic" | "ollama" | null; model: string | null; local: boolean };

export type Analysis = {
  scenario_id: string | null;
  band: Band;
  trust_score: number;
  trust_low: number;
  trust_high: number;
  required_trust: number;
  impact: number;
  signals: Signal[];
  checks: Check[];
  could_not_check: string[];
  verification_steps: string[];
  summary: string;
  reasoning: Reasoning | null;
  is_placeholder: boolean;
};

export type ScenarioSummary = { id: string; title: string; description: string; simulated: boolean };

export type ScenarioDetail = ScenarioSummary & {
  event: {
    action: { type: string; amount: number | null; payee: string | null };
    evidence: { chat: { sender_claimed: string; text: string } | null };
  };
};

export type DocumentReport = {
  filename: string;
  format: string;
  size_bytes: number;
  fields: Record<string, string>;
  signals: Signal[];
  could_not_check: string[];
  summary: string;
};
