import type { ClaudeReviewPayload } from "@/components/options/types";

/** Mirrors src/api/models (portfolio.py AccountValueResponse, pnl.py MonthPayResponse,
 *  DayTradesResponse and RealisedCalendarResponse, spreads.py SpreadPositionsResponse).
 *  Hand-written like components/<domain>/types.ts. */

export type RangeKey = "1d" | "1w" | "1m" | "3m" | "ytd" | "all";

export type AccountValuePoint = { at: string; value: number };

export type AccountValueSeries = {
  range: RangeKey;
  points: AccountValuePoint[];
  latest: number | null;
  latest_at: string | null;
  previous_close: number | null;
  /** Null whenever the headline value is not from today (weekend, before the first snapshot). */
  change_today: number | null;
  change_today_pct: number | null;
  /** The headline's move over the selected range (1d: the last session's, so a weekend still
   *  shows Friday's). Null only when there is no earlier known value. */
  change: number | null;
  change_pct: number | null;
  change_since: string | null;
};

export type AccountValueResponse = { as_of: string; series: AccountValueSeries };

export type MonthPay = {
  month: string;
  strategy: "all" | "csp" | "cc" | "spread" | "value";
  premium_collected: number;
  bought_back: number;
  commissions: number;
  commissions_complete: boolean;
  net: number;
  n_opened: number;
  n_closed: number;
  month_start_value: number | null;
  target_pct: number | null;
  /** How the target is set; "off" means no target. */
  target_mode: "off" | "fixed" | "pct_of_account" | "pct_of_amount";
  target_amount: number | null;
  target_base: number | null;
  target: number | null;
  progress_pct: number | null;
  days_left: number;
  /** The value book's realised result on sales this month; null when nothing was sold. Never part of `net`
   *  under All (the income target counts options income only). */
  value_realised?: number | null;
  /** Null: value.db holds no commissions, so none are known. */
  value_commissions?: number | null;
  value_commissions_complete?: boolean;
  value_n_closed?: number;
};

export type MonthPayResponse = {
  as_of: string;
  book: "paper" | "live";
  pay: MonthPay;
  /** False when a spreads book is in scope but data/spreads.db could not be read. */
  spreads_available: boolean;
  /** False when the value book is in scope but data/value.db could not be read. */
  value_available?: boolean;
};

export type SpreadPosition = {
  as_of: string;
  spread_id: string;
  mode: string;
  side: "put" | "call";
  expiry: string;
  short_strike: number;
  long_strike: number;
  width: number;
  contracts_opened: number;
  contracts: number;
  entry_credit: number;
  entry_commission: number;
  opened_at: string;
  status: string;
  exit_debit: number | null;
  exit_commission: number | null;
  exit_reason: string | null;
  closed_at: string | null;
  realized_pnl_usd: number | null;
};

export type SpreadPositionsResponse = {
  as_of: string;
  available: boolean;
  underlying: string;
  mode: string;
  positions: SpreadPosition[];
};

export type DayTradeAction = "opened" | "closed" | "rolled";
export type DayTradeHow = "bought_back" | "expired" | "assigned" | "called_away" | "rolled";

export type DayFact = { label: string; text: string; source: "system" | "claude" };

export type DayRolledTo = {
  candidate_id: string;
  strike: number;
  expiry: string;
  contracts: number;
  premium: number | null;
  commissions: number | null;
};

/** One executed trade on one New York day (src/common/schemas.py DayTrade). Money is USD for the
 *  whole position and positive; null is unknown, never 0. */
export type DayTrade = {
  key: string;
  action: DayTradeAction;
  how: DayTradeHow | null;
  kind: "csp" | "cc" | "spread" | "value" | "other";
  source: "wheel" | "spreads" | "value";
  underlying: string;
  right: "C" | "P" | null;
  strike: number;
  long_strike: number | null;
  expiry: string;
  contracts: number;
  at: string;
  is_live: boolean;
  premium: number | null;
  bought_back: number | null;
  commissions: number | null;
  commissions_complete: boolean;
  net_pnl: number | null;
  capital: number | null;
  roc_pct: number | null;
  annualized_pct: number | null;
  pct_kept: number | null;
  dte_at_open: number | null;
  days_held: number | null;
  reason: string | null;
  facts: DayFact[];
  approval_id: number | null;
  decided_by?: "system" | "web" | "telegram" | null;
  review: ClaudeReviewPayload | null;
  rolled_to: DayRolledTo | null;
};

export type DayTradesResponse = {
  as_of: string;
  date: string;
  book: "paper" | "live";
  strategy: "all" | "csp" | "cc" | "spread" | "value";
  trades: DayTrade[];
  spreads_available: boolean;
  value_available?: boolean;
  previous_day?: string | null;
  next_day?: string | null;
};

export type CalendarDay = { date: string; realized: number; n_closed: number; complete: boolean };

export type MonthCalendar = {
  month: string;
  strategy: "all" | "csp" | "cc" | "spread" | "value";
  days: CalendarDay[];
  total: number;
  n_closed: number;
  complete: boolean;
};

export type RealisedCalendarResponse = {
  as_of: string;
  book: "paper" | "live";
  calendar: MonthCalendar;
  spreads_available: boolean;
  value_available?: boolean;
};
