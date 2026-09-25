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

export type HeaderSummary = {
  from_display: string;
  from_email: string | null;
  reply_to: string | null;
  subject: string;
  spf: string | null;
  dkim: string | null;
  dmarc: string | null;
  sending_ip: string | null;
  sending_host: string | null;
};

export type OfficialContact = { organisation: string; domains: string[]; site: string; kind: string };
export type FollowUp = { id: "sender_email" | "organisation"; question: string };

export type SandboxStatus = { setting: string; mode: "container" | "none"; image_ready: boolean };

export type Config = { reasoning_enabled: boolean; provider: "gemini" | "anthropic" | "ollama" | null; model: string | null; local: boolean; sandbox: SandboxStatus };

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
  official_contact: OfficialContact | null;
  header_summary: HeaderSummary | null;
  isolation: string;
  follow_ups: FollowUp[];
  is_placeholder: boolean;
  risk: RiskSummary | null;
};

export type Identifier = { kind: string; value: string; valid: boolean | null; note: string };
export type DocumentFacts = {
  document_type: string;
  issuer: string | null;
  recipient: string | null;
  total_amount: string | null;
  account_holder: string | null;
  dates: string[];
  payment_details: string[];
};
export type ContentReport = {
  extracted: boolean;
  characters: number;
  truncated: boolean;
  pages: number | null;
  links: string[];
  identifiers: Identifier[];
  excerpt: string;
  notes: string[];
  reading: Reasoning | null;
  facts: DocumentFacts | null;
};

export type DocumentReport = {
  filename: string;
  format: string;
  size_bytes: number;
  fields: Record<string, string>;
  signals: Signal[];
  could_not_check: string[];
  summary: string;
  isolation: string;
  content: ContentReport | null;
  band: Band | null;
  verification_steps: string[];
  risk: RiskSummary | null;
};

export type RiskFactor = { id: string; label: string; area: string; likelihood: number; impact: number; weight: number; source: string };
export type RiskArea = { name: string; risk: number; suspicious: number; reassuring: number; unknown: number };
export type RiskPart = { name: string; risk_score: number; verdict: string };
export type RiskSummary = {
  risk_score: number;
  security_score: number;
  verdict: "legit" | "suspicious" | "not_legit";
  verdict_label: string;
  level: "low" | "medium" | "high" | "critical";
  band: Band;
  areas: RiskArea[];
  matrix: RiskFactor[];
  suspicious: number;
  reassuring: number;
  unknown: number;
  parts: RiskPart[];
  basis: string;
};

export type EmailResult = { message: Analysis | null; attachment: DocumentReport | null; risk: RiskSummary | null };
