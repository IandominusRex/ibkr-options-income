import Link from "next/link";
import { Card } from "@/components/ui/Card";

type Where = { href: string; label: string };
type Part = { id: string; title: string; body: string[]; where: Where[] };

/**
 * How it works (web overhaul Part 7, the operator's answer: rebuild small). Seven short sections of static
 * plain English, each ending with the console pages that show it. Every sentence is traceable to root
 * CLAUDE.md or the code; change the copy here when the system changes (STATUS.md is the record).
 */
export const PARTS: Part[] = [
  {
    id: "day",
    title: "A day, from scan to order",
    body: [
      "During US market hours Python scans the names in your universe, reads their option chains and scores covered calls and cash-secured puts.",
      "The Rules Engine checks every candidate against your limits. Only what passes becomes a proposal.",
      "Claude reviews the proposals and writes a note on each. You approve or reject on Trades or in Telegram, unless the autonomy setting lets the system approve for you.",
      "Before an order is sent, the Rules Engine checks it again against a fresh quote. Then a limit order at mid goes to Interactive Brokers.",
    ],
    where: [{ href: "/trades", label: "Trades" }, { href: "/", label: "Home" }],
  },
  {
    id: "decides",
    title: "Who decides what",
    body: [
      "The Rules Engine is plain Python with no model in it, and it is the only path to an order.",
      "Claude reviews and ranks. It never places, prices or gates an order, and a malformed reply falls back to Python's list.",
      "Two written exceptions: Claude may lower, never raise, the contract count of a cash-secured put the system opens on its own; and in the value book, on a name that already passed every Python gate, Claude's verdict decides Ready, Watch, Wait or No, with its fair value worked out by Python from Claude's inputs and capped at one and a half times Python's own. Both apply in paper and are only recorded in live until you have reviewed them.",
      "You decide approvals, the autonomy setting, a halt, and which names are on the would-own list and the watchlist.",
    ],
    where: [{ href: "/more/claude", label: "What Claude knows" }, { href: "/research/universe", label: "Universe" }],
  },
  {
    id: "books",
    title: "Three books in one account",
    body: [
      "The wheel sells covered calls and cash-secured puts on the names in your universe.",
      "Credit spreads trade daily SPY spreads in their own process with their own gate. Claude may pick from a menu Python built and checked, never beyond it. Paper only for now.",
      "The value book buys and sells shares of companies scored from their filings, apart from the wheel's shares. Paper only for now.",
      "Beside them, the news service explains market and company news on its own thread. It holds no positions and never trades.",
    ],
    where: [{ href: "/portfolio", label: "Portfolio" }, { href: "/research", label: "Research" }, { href: "/news", label: "News" }],
  },
  {
    id: "sizing",
    title: "Sizing and the market",
    body: [
      "Python reads the market's regime from SPY, QQQ and the VIX and uses it to size new cash-secured puts, and to hold some back when the market is weak.",
      "The Market card on Home, Trades and News says what the regime does to new puts today. Python sets every size; Claude can only lower the count of a put the system opens on its own, as above.",
    ],
    where: [{ href: "/more/claude", label: "What Claude knows" }, { href: "/activity?view=system", label: "Activity, System" }],
  },
  {
    id: "rolls",
    title: "Rolls, assignment and freeing cash",
    body: [
      "When a short option comes under pressure, Python's roll policy decides whether to roll, take assignment, let the shares be called away, close or hold. The Rules Engine checks every roll against the roll limits in your settings.",
      "When the value book wants to buy and the account is short of cash, the trading service may close the fewest wheel cash-secured puts at breakeven or better to free it. Paper only. That buy can follow a Ready that Claude's verdict decided, and a release needs no tap of its own: it inherits the buy's approval. Python checks every step twice, and the close never pays more than the entry credit less the required profit.",
    ],
    where: [{ href: "/trades", label: "Trades" }, { href: "/portfolio", label: "Portfolio" }],
  },
  {
    id: "safety",
    title: "What keeps it safe",
    body: [
      "Paper first: live trading needs a setting in the private environment file and the live port, and the console says which mode it is in.",
      "A halt from the console stops new wheel and value-book orders until you lift it; credit spreads have their own halt. Circuit breakers pause trading after losses. Every act on this console is a request that one of the system's services carries out after its own checks; the console never sends an order itself.",
    ],
    where: [{ href: "/more", label: "More" }, { href: "/activity?view=fills", label: "Activity, Fills and orders" }],
  },
  {
    id: "pages",
    title: "Where to look",
    body: [
      "Home is today: the account, what needs you and the market. Trades holds the proposals and the day's history. Portfolio is what you hold. Activity is your pay, the fills and the ledger. Research is what the value book would buy, your watchlist and the sectors. News is the feed and the calendar.",
    ],
    where: [
      { href: "/", label: "Home" },
      { href: "/trades", label: "Trades" },
      { href: "/portfolio", label: "Portfolio" },
      { href: "/activity", label: "Activity" },
      { href: "/research", label: "Research" },
      { href: "/news", label: "News" },
    ],
  },
];

export function ExplainPage() {
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
      <header className="mt-1">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">How it works</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-muted">
          The system in plain English: what runs, who decides, and where to see it on this console.
        </p>
      </header>
      <div className="mt-6 grid max-w-[820px] grid-cols-1 gap-4">
        {PARTS.map((p) => (
          <Card key={p.id} aria-labelledby={`explain-${p.id}`}>
            <h2 id={`explain-${p.id}`} className="text-[1.0625rem] font-bold">
              {p.title}
            </h2>
            <div className="mt-2 max-w-[65ch] space-y-2 text-sm">
              {p.body.map((b) => (
                <p key={b}>{b}</p>
              ))}
            </div>
            <p className="mt-3 flex flex-wrap items-center gap-x-4 text-[0.8125rem]">
              <span className="text-muted">See it on</span>
              {p.where.map((w) => (
                <Link
                  key={w.href}
                  href={w.href}
                  className="flex min-h-11 items-center font-semibold underline underline-offset-2 md:inline md:min-h-0"
                >
                  {w.label}
                </Link>
              ))}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
