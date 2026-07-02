// Thin API client. Injects the dev-user header (stand-in for OIDC until M10).

export const API = "/api/v1";

export const DEV_USERS = [
  { email: "reviewer@dev.local", label: "Reviewer" },
  { email: "approver@dev.local", label: "Approver" },
  { email: "admin@dev.local", label: "Admin" },
];

export function getDevUser(): string {
  return localStorage.getItem("devUser") || "admin@dev.local";
}
export function setDevUser(email: string): void {
  localStorage.setItem("devUser", email);
}

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(message: string, status: number, data: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Dev-User": getDevUser() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail ?? res.statusText;
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status, data);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b),
};

// --- types (mirror the backend schemas) ---------------------------------------

export interface Me {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
}

export interface Source {
  id: string;
  cloud: string;
  display_name: string;
  scope: string;
  enabled: boolean;
}

export interface Policy {
  approved_regions: Record<string, string[]>; // { azure: [...], gcp: [...] }
  updated_at: string;
}

export interface FrameworkReference {
  label: string | null;
  doc: string | null;
  url: string | null;
}

export interface FrameworkStatus {
  id: string;
  name: string;
  rmf_version: string | null;
  effective_date: string | null;
  references: FrameworkReference[];
  questionnaire_version: number;
  control_count: number;
  last_reviewed_at: string | null;
  reviewed_by: string | null;
  review_interval_days: number;
  next_review_due: string | null;
  overdue: boolean;
  notes: string | null;
  update_available: boolean;
  latest_known_version: string;
}

export interface UpdateCheck {
  implemented_version: string;
  latest_known_version: string;
  latest_published: string;
  latest_label: string;
  latest_url: string;
  latest_notes: string;
  up_to_date: boolean;
  checked_at: string;
}

export interface DiscoveredModel {
  vendor: string;
  model_name: string;
  model_version: string | null;
  resource_id: string;
  regions: string[];
  label: string;
}

export interface ModelOut {
  id: string;
  cloud: string;
  vendor: string;
  model_name: string;
  model_version: string | null;
  resource_id: string;
  regions: string[];
  status: string;
  latest_score: number | null;
  latest_tier: number | null;
  current_review_id: string | null;
}

export interface Gate {
  type: string;
  control_id: string;
  control_key: string;
  answer: string;
  reason: string;
}

export interface RiskScore {
  id: string;
  review_id: string;
  overall_score: number;
  tier: number;
  tier_label: string;
  function_deficits: Record<string, number>;
  triggered_gates: Gate[];
  is_current: boolean;
}

export interface Control {
  id: string;
  control_key: string;
  control_id: string;
  nist_control: string | null;
  nist_url: string | null;
  nist_function: string;
  question_text: string;
  evidence_needed: string | null;
  weight: string;
  gai_categories: string[];
  is_ko: boolean;
  owner: "platform" | "use_case";
  answer: string | null;
  evidence_url: string | null;
  evidence_note: string | null;
  answer_source: string | null; // auto | attested | suggested | human | carried | null(manual)
  auto_answer: string | null;
  auto_rationale: string | null;
  auto_confidence: string | null;
}

export interface Review {
  id: string;
  model_id: string;
  framework: string;
  state: string;
  trigger: string;
  assigned_reviewer_id: string | null;
  assigned_approver_id: string | null;
  opened_at: string;
  submitted_at: string | null;
  decided_at: string | null;
  precedent_review_id: string | null;
}

export interface ModelTerms {
  id: string | null;
  label: string | null;
  url: string | null;
}

export interface PrecedentRef {
  review_id: string;
  model_id: string;
  model_name: string;
  model_version: string | null;
  cloud: string;
  decision_state: string;
  decided_at: string | null;
  tier: number | null;
  score: number | null;
  terms: ModelTerms | null;
}

export interface Precedent {
  available: boolean;
  reasons: string[];
  model_terms: ModelTerms | null;
  precedent: PrecedentRef | null;
  carryable_keys: string[];
  carryable_count: number;
}

export interface AdoptResult {
  precedent_review_id: string;
  carried_keys: string[];
  carried_count: number;
}

export interface ReviewDetail extends Review {
  model: ModelOut;
  controls: Control[];
  current_score: RiskScore | null;
}

export interface Decision {
  id: string;
  decision: string;
  justification: string;
  conditions: string | null;
  overridden_tier: number | null;
  override_reason: string | null;
  decided_at: string;
}

export const TIER_CLASS: Record<number, string> = { 1: "t1", 2: "t2", 3: "t3", 4: "t4" };
