/**
 * The console's own pages, for the search palette (web overhaul Part 6, operator ruling: tickers plus
 * the console's pages, from a fixed list in the web, no API change). Each entry is a place you can go,
 * named as the page names itself, with the words someone might type for it.
 */
export type PageHit = { label: string; href: string; hint: string; words: string[] };

export const PAGES: PageHit[] = [
  { label: "Home", href: "/", hint: "Account value, pay and positions", words: ["account", "dashboard"] },
  { label: "Trades", href: "/trades", hint: "Proposals, history and assessed", words: ["approve", "proposals"] },
  { label: "Trades, History", href: "/trades?view=history", hint: "One day's trades", words: ["orders", "fills", "working"] },
  { label: "Trades, Assessed", href: "/trades?view=assessed", hint: "Every contract the last scan looked at", words: ["scan", "candidates", "promote"] },
  { label: "Trades, Credit spreads", href: "/trades?strategy=spread", hint: "The day's spreads by book", words: ["spreads", "spy", "picks"] },
  { label: "Portfolio", href: "/portfolio", hint: "Positions by name", words: ["positions", "holdings", "account"] },
  { label: "Portfolio, Campaigns", href: "/portfolio?view=campaigns", hint: "Each wheel from first put", words: ["wheel", "campaign"] },
  { label: "Portfolio, Calendar", href: "/portfolio?view=calendar", hint: "What expires when", words: ["expiry", "expiries"] },
  { label: "Activity, Pay", href: "/activity", hint: "A month's pay as a stub", words: ["income", "pnl", "month"] },
  { label: "Activity, Ledger", href: "/activity?view=ledger", hint: "IBKR's trades and per-ticker roll-ups", words: ["broker", "trades"] },
  { label: "Activity, Fills and orders", href: "/activity?view=fills", hint: "Orders, fills and executions", words: ["orders", "executions", "fills"] },
  { label: "Activity, System", href: "/activity?view=system", hint: "Sizing record and score against outcome", words: ["sizing", "score"] },
  { label: "Research", href: "/research", hint: "Top opportunities, your watchlist, sectors", words: ["value", "watchlist", "sectors"] },
  { label: "Universe", href: "/research/universe", hint: "The names the scan covers", words: ["would own", "watchlist", "scan"] },
  { label: "News", href: "/news", hint: "Feed and calendar", words: ["headlines", "earnings", "calendar"] },
  { label: "What Claude knows", href: "/more/claude", hint: "The market picture and what each call reads", words: ["regime", "picture", "limits"] },
  { label: "How it works", href: "/explain", hint: "The pipeline in plain English", words: ["explain", "help"] },
  { label: "Import a statement", href: "/ledger/import", hint: "Upload an IBKR activity CSV", words: ["csv", "upload"] },
  { label: "More", href: "/more", hint: "Bot, theme, income target, system status", words: ["settings", "halt", "target", "theme"] },
];

const MAX_PAGES = 5;

/**
 * The pages whose name or words contain every word typed (case ignored), best first: a name that
 * starts with the term, then a name that contains it, then a match on the words alone. A blank term
 * finds nothing, as the ticker search does.
 */
export function matchPages(term: string, pages: PageHit[] = PAGES): PageHit[] {
  const q = term.trim().toLowerCase();
  if (!q) return [];
  const parts = q.split(/\s+/);
  const rank = (p: PageHit): number => {
    const label = p.label.toLowerCase();
    const all = [label, p.hint.toLowerCase(), ...p.words].join(" ");
    if (!parts.every((w) => all.includes(w))) return -1;
    if (label.startsWith(q)) return 0;
    if (label.includes(q)) return 1;
    return 2;
  };
  return pages
    .map((p, i) => ({ p, i, r: rank(p) }))
    .filter((x) => x.r >= 0)
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .slice(0, MAX_PAGES)
    .map((x) => x.p);
}
