export type Verdict = "further_downside_likely" | "further_upside_likely" | "overreaction_likely" | "priced_in" | "unclear";
export type SourceLink = { name: string; url: string };
export type GridRow = { asset: string; textbook: string | null; actual: string | null };
export type Explanation = {
  headline: string; what_happened: string; read: string; bull: string; bear: string;
  verdict: Verdict; confidence: "low" | "medium" | "high"; book_impact: string; setup_impact: string; evidence: string[];
};
export type DigestItem = { text: string; read?: string | null; verdict?: Verdict | null; links: SourceLink[] };
export type DigestSection = { title: string; items: DigestItem[] };
export type CardPayload = {
  kind: string; subject?: string | null; title: string; emoji: string; when: string;
  headline_line?: string | null; facts_line?: string | null; grid: GridRow[]; grid_note?: string | null;
  explanation?: Explanation | null; trimmed?: boolean; llm_note?: string | null; regime?: string | null;
  sections: DigestSection[]; links: SourceLink[]; image_url?: string | null; updates: string[];
};
export type NewsPost = {
  id: number; kind: string; subject: string | null; posted_at: string; stage: string;
  critical: boolean; silent: boolean; has_chart: boolean; payload: CardPayload;
};
export type NewsFeedResponse = { as_of: string; available: boolean; posts: NewsPost[] };
export type EconEvent = { title: string; scheduled_at: string; impact: string; forecast: string | null; previous: string | null; actual: string | null; surprise_dir: string | null };
export type Earnings = { symbol: string; report_date: string; timing: string; eps_est: number | null; eps_actual: number | null; status: string; held: boolean };
export type NewsCalendarResponse = { as_of: string; available: boolean; econ: EconEvent[]; earnings: Earnings[] };
export type Cluster = { id: number; headline: string; source_count: number; last_seen: string; links: SourceLink[] };
export type NewsTickerResponse = {
  as_of: string; available: boolean; symbol: string; latest_brief: NewsPost | null; clusters: Cluster[];
  next_earnings: Earnings | null; request: { id: number; status: string; requested_at: string; post_id: number | null; error: string | null } | null;
};
export type NewsPostDetail = { as_of: string; available: boolean; post: NewsPost; chart_data_uri: string | null };
