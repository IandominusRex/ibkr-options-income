// Hand-mirrors the Ledger* models in src/common/schemas.py and src/api/models/ledger.py.
// Keep in step with those files when they change (these are not generated).

export type LedgerOutcome =
  | "Open" | "Pending" | "Expired" | "Assigned" | "Called away"
  | "Exercised" | "Bought back" | "Sold" | "Rolled";

export const OUTCOMES: LedgerOutcome[] = [
  "Open", "Pending", "Expired", "Assigned", "Called away", "Exercised", "Bought back", "Sold", "Rolled",
];

export type LedgerClose = {
  order_key: string; close_date: string; close_time: string; quantity: number;
  cash: number; commission: number; codes: string;
};

export type LedgerTrade = {
  order_key: string; underlying: string; currency: string; side: "Sell" | "Buy";
  right: "P" | "C"; strike: number; expiry: string; multiplier: number; lots: number;
  order_date: string; open_time: string; close_date: string | null; dte: number; days_held: number;
  premium: number; open_commission: number; closes: LedgerClose[]; outcome: LedgerOutcome;
  computed_outcome: LedgerOutcome; outcome_overridden: boolean; mixed_close: boolean;
  capital: number; pct_profit: number | null; net_pnl: number | null; return_pct: number | null;
  annualised_net_pct: number | null; stock_gain: number | null; book: "system" | "manual";
  rolled_from: string | null; rolled_to: string | null; ibkr_realized_pnl: number | null;
  exec_row_ids: number[]; notes: string; tags: string[]; exclude_from_stats: boolean;
};

export type LedgerTicker = {
  symbol: string; currency: string; option_premium_gross: number; option_net_pnl: number;
  stock_realized: number; dividends_net: number; total_realized: number; unrealized: number | null;
  n_trades: number; n_open: number; n_closed: number; win_rate: number | null;
  avg_premium: number | null; best_trade: number | null; worst_trade: number | null;
  annualised_return_pct: number | null; shares_held: number; broker_avg_cost: number | null;
  wheel_adjusted_basis: number | null; first_trade: string | null; last_trade: string | null;
};

export type LedgerMonth = { month: string; premium_usd: number; realized_usd: number };
export type LedgerCurvePoint = { point_date: string; cumulative_usd: number };
export type LedgerBucket = { label: string; n_closed: number; realized_usd: number; win_rate: number | null };

export type LedgerSummary = {
  total_realized_usd: number; interest_and_fees_usd: number; contributed_usd: number | null;
  capital_utilised_usd: number; available_usd: number | null; unrealized_usd: number | null;
  win_rate: number | null; n_trades: number; n_open: number; premium_this_month_usd: number;
  months: LedgerMonth[]; curve: LedgerCurvePoint[]; by_strategy: LedgerBucket[];
  by_book: LedgerBucket[]; upcoming: LedgerTrade[]; fx_incomplete: boolean; orphan_closes: number;
  unreviewed_corporate_actions: number; marks_as_of: string | null;
};

export type LedgerStockLot = {
  lot_key: string; underlying: string; currency: string; acquired_date: string;
  source: "bought" | "assigned" | "exercised"; quantity: number; remaining: number; cost_per_share: number;
};
export type LedgerStockDisposal = {
  lot_key: string; underlying: string; currency: string; disposal_date: string;
  quantity: number; price: number; realized: number; codes: string;
};
export type LedgerCashItem = {
  event_date: string; event_type: string; currency: string; amount: number;
  description: string; underlying: string | null;
};
export type LedgerBasisPoint = { point_date: string; label: string; basis_per_share: number };
export type LedgerTickerDetail = {
  ticker: LedgerTicker; trades: LedgerTrade[]; lots: LedgerStockLot[];
  disposals: LedgerStockDisposal[]; dividends: LedgerCashItem[]; basis_walk: LedgerBasisPoint[];
};

export type LedgerExecution = {
  id: number; source: string; source_kind: string; exec_id: string | null; trade_time: string;
  quantity: number; price: number; proceeds: number; commission: number; codes: string;
  book: string; superseded_by: number | null;
};
export type LedgerImportRun = {
  id: number; source: string; filename: string | null; started_at: string; finished_at: string | null;
  status: string; reason: string | null; counts: Record<string, number>;
  errors: { line?: number; section?: string; message?: string }[];
};
export type LedgerFeedStatus = {
  configured: boolean; last_run: string | null; last_status: string | null; last_error: string | null;
};
export type LedgerCorporateAction = {
  id: number; event_date: string; underlying: string | null; description: string;
  quantity: number; proceeds: number; reviewed: boolean;
};

export type LedgerSummaryResponse = { as_of: string; summary: LedgerSummary };
export type LedgerTickersResponse = { as_of: string; tickers: LedgerTicker[] };
export type LedgerTickerResponse = { as_of: string; detail: LedgerTickerDetail };
export type LedgerTradesResponse = {
  as_of: string; n: number; trades: LedgerTrade[]; filters: Record<string, string | null>;
};
export type LedgerTradeResponse = { as_of: string; trade: LedgerTrade; executions: LedgerExecution[] };
export type LedgerImportsResponse = {
  as_of: string; runs: LedgerImportRun[]; flex: LedgerFeedStatus; sheets: LedgerFeedStatus;
  corporate_actions: LedgerCorporateAction[];
};
