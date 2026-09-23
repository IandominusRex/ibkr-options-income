// Shared vocabulary for the System Explanation tab. One `TabKey` per subtab; `TAB_META`
// gives every other component (the shell's tab bar, the pipeline map, the ties-into chips)
// a single source of truth for labels so they can never drift out of sync with each other.

export type TabKey =
  | "overview"
  | "data"
  | "ideas"
  | "gate"
  | "claude"
  | "execution"
  | "watching"
  | "web";

export const TAB_META: Record<TabKey, { label: string; short: string }> = {
  overview: { label: "Overview", short: "Overview" },
  data: { label: "Data In", short: "Data" },
  ideas: { label: "Finding Trades", short: "Ideas" },
  gate: { label: "The Risk Gate", short: "Gate" },
  claude: { label: "Claude's Role", short: "Claude" },
  execution: { label: "Approval & Execution", short: "Approve" },
  watching: { label: "Watching & Adjusting", short: "Watching" },
  web: { label: "This Dashboard", short: "Dashboard" },
};

export const TAB_ORDER: TabKey[] = [
  "overview",
  "data",
  "ideas",
  "gate",
  "claude",
  "execution",
  "watching",
  "web",
];

export type TieIn = { tab: TabKey; reason: string };

// A file path plus a one-line note on what lives there, rendered by <SourceRefs/> at the
// foot of every panel — the bridge from "here's the simple version" back to the real code
// and the exhaustive docs (ARCHITECTURE.md / STATUS.md), for whoever wants to go deeper.
export type SourceRef = { path: string; note: string };
