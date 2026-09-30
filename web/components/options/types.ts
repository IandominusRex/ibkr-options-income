// Shared types for the options console, matching the API response shapes in
// src/api/models/options.py. Kept inline rather than generated because the
// options routes are new and `npm run gen:api` will pick them up on the next
// regeneration pass.

export type ApprovalSummary = {
  as_of: string;
  id: number;
  candidate_id: string;
  status: "pending" | "approved" | "rejected" | "expired";
  underlying: string;
  strategy: string;
  right: string;
  strike: number;
  expiry: string | null;
  contracts: number;
  premium: number | null;
  blended_score: number | null;
  created_at: string;
  expires_at: string | null;
  decided_at: string | null;
  order_state: string | null;
  source: "scan" | "roll";
  review: ClaudeReviewPayload | null;
  /** Frozen candidate tags, e.g. `iv_rank_unavailable` (display only). */
  rationale_tags?: string[];
};

export type IdealZonePayload = {
  lo: number | null;
  hi: number | null;
  min_credit: number | null;
};

export type ClaudeReviewPayload = {
  why_attractive: string;
  risks: string;
  tradeoffs: string;
  assignment_considerations: string;
  rolling_considerations: string;
  recommendation?: string | null;
  priority?: number | null;
  confidence?: number | null;
  /** 2-3 sentence plain-English verdict (empty on reviews stored before it existed). */
  summary?: string;
  /** Ids the verdict cites: `F#` = a computed fact, `N#` = a news headline. */
  evidence?: string[];
};

export type AlternativeStrike = {
  candidate_id: string;
  strategy: string;
  strike: number;
  expiry: string | null;
  right?: string | null;
  blended_score: number | null;
  premium: number | null;
  stage: string | null;
  reasons: string[];
};

export type ApprovalDetail = ApprovalSummary & {
  snapshot: Record<string, unknown>;
  ideal: IdealZonePayload | null;
  gate_reasons: string[];
  alternatives: AlternativeStrike[];
  order_id: number | null;
  fills: FillSummary[];
};

export type ApprovalListResponse = { as_of: string; approvals: ApprovalSummary[] };

export type AssessedStage =
  | "generator"
  | "risk_gate"
  | "score_floor"
  | "dedupe"
  | "top_n"
  | "passed";

export type AssessedContract = {
  as_of: string;
  candidate_id: string;
  symbol: string;
  strategy: string;
  strike: number | null;
  expiry: string | null;
  stage: AssessedStage;
  reasons: string[];
  reasons_text: string[];
  blended_score: number | null;
  premium: number | null;
  ideal: IdealZonePayload | null;
  promotable: boolean;
  promote_note: string | null;
};

export type AssessedGroup = {
  as_of: string;
  symbol: string;
  contracts: AssessedContract[];
  counts: Record<string, number>;
};

export type AssessedResponse = {
  as_of: string;
  run_id: string | null;
  computed_at: string | null;
  groups: AssessedGroup[];
};

export type OrderSummary = {
  as_of: string;
  id: number;
  candidate_id: string;
  approval_id: number | null;
  underlying: string;
  strategy: string;
  strike: number;
  expiry: string | null;
  state: "queued" | "submitted" | "filled" | "partial" | "cancelled" | "rejected";
  limit_price: number | null;
  filled_qty: number;
  avg_fill_price: number | null;
  is_live: boolean;
  detail: string | null;
  created_at: string;
  updated_at: string;
};

export type OrderListResponse = { as_of: string; orders: OrderSummary[] };

export type FillSummary = {
  as_of: string;
  id: number;
  order_id: number;
  candidate_id: string;
  action: string;
  filled_qty: number;
  avg_price: number;
  commission: number | null;
  is_live: boolean;
  filled_at: string;
};

export type FillListResponse = { as_of: string; fills: FillSummary[] };

export type RollAlertSummary = {
  id: number;
  trigger: string;
  trigger_label: string;
  detail: string;
  claude_recommendation: string | null;
  created_at: string;
};

export type SourcedDelta = {
  value: number | null;
  source: string;
  as_of: string;
  stale: boolean;
};

export type ShortPosition = {
  as_of: string;
  position_symbol: string;
  underlying: string;
  right: "C" | "P";
  strike: number;
  expiry: string | null;
  dte: number | null;
  contracts: number;
  avg_cost: number | null;
  mark: number | null;
  unrealized_pnl: number | null;
  pnl_pct: number | null;
  delta: SourcedDelta | null;
  assignment_risk: boolean;
  alerts: RollAlertSummary[];
};

export type ShortListResponse = { as_of: string; shorts: ShortPosition[] };

export type ControlsResponse = {
  as_of: string;
  autonomy: { level: string; label: string };
  rungs: { level: string; label: string }[];
  halted: boolean;
  halt_reason: string | null;
  halted_at: string | null;
  mode: "paper" | "live";
  drain_healthy: boolean;
  drain_last_seen: string | null;
  pending_commands: number;
};