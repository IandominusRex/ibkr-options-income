/** The Portfolio page's views (web/DESIGN.md Surfaces → Portfolio). */
export type PortfolioView = "positions" | "campaigns" | "calendar";

export const PORTFOLIO_VIEWS: readonly PortfolioView[] = ["positions", "campaigns", "calendar"];

export const VIEW_LABEL: Record<PortfolioView, string> = {
  positions: "Positions",
  campaigns: "Campaigns",
  calendar: "Calendar",
};
