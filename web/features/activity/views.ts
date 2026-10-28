/** The Activity page's views (web/DESIGN.md Surfaces → Activity). */
export type ActivityView = "pay" | "ledger" | "fills" | "system";

export const ACTIVITY_VIEWS: readonly ActivityView[] = ["pay", "ledger", "fills", "system"];

export const VIEW_LABEL: Record<ActivityView, string> = {
  pay: "Pay",
  ledger: "Ledger",
  fills: "Fills and orders",
  system: "System",
};
