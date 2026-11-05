import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import type { ValueNextExit, ValueProposalLike } from "./types";

const WHOLE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const COUNT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** "$7,200" for a ceiling or a sum; n/a for a figure we do not have, never $0. */
export function wholeDollars(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return UNKNOWN;
  return `${v < 0 ? "-" : ""}$${WHOLE.format(Math.abs(v))}`;
}

/** "$180.00" for a price. */
export function price(v: number | null | undefined): string {
  return formatMoneyCell(v);
}

/** "20" or "12.5": a share count without trailing zeros. */
export function shareCount(v: number): string {
  return COUNT.format(v);
}

export function sharesWord(v: number): string {
  return `${shareCount(v)} share${v === 1 ? "" : "s"}`;
}

/** The ceiling used as a sum: "$7,200 of $30,000". A side we do not have reads n/a. */
export function ceilingSum(used: number | null | undefined, ceiling: number | null | undefined): string {
  return `${wholeDollars(used)} of ${wholeDollars(ceiling)}`;
}

/** The next exit level in words: "sell half at $180.00". Null when the book has not set one. */
export function nextExitWords(exit: ValueNextExit | null | undefined): string | null {
  if (!exit) return null;
  return `${exit.kind === "stop" ? "stop" : "sell half"} at ${price(exit.level)}`;
}

const LIST_WORDS: Record<string, string> = {
  deep_value: "Deep value",
  quality_growth: "Quality growth",
};

export function listWords(name: string): string {
  return LIST_WORDS[name] ?? name.replace(/_/g, " ");
}

// The proposal's reason codes (src/value/book.py, live.py), in words. Mirrors src/value/cards.py.
const REASON_WORDS: Record<string, string> = {
  arm: "the trailing stop armed",
  half: "the price reached fair value: sell half and tighten the stop on the rest",
  stop: "the stop was hit",
  trail: "the trailing stop was hit",
  peak: "the peak signal fired",
  thesis: "a thesis exit fired",
  remark: "fair value was re-marked",
  remark_below: "fair value fell below the price",
  catastrophe: "the catastrophe stop was hit",
  time: "the holding period ended",
  proposal: "an exit proposal",
  shock: "a shock stop fired",
  drawdown_trim: "the book's drawdown passed its trim line: trimming every holding to half",
  claude_broken: "Claude's review of the held name returned BROKEN",
  claude_no: "Claude's verdict on the name turned NO",
};

// Why a command did not apply (the value process's reasons, src/value/cards.py).
const FAILURE_WORDS: Record<string, string> = {
  not_paper: "The book trades in paper only.",
  expired: "The proposal expired before the tap.",
  no_such_proposal: "That proposal no longer exists.",
  handler_error: "The value process hit an error.",
};

export function reasonWords(code: string): string {
  const tranche = /^tranche (\d+)$/.exec(code);
  if (tranche) return `scaling in, tranche ${tranche[1]}`;
  return REASON_WORDS[code] ?? code.replace(/_/g, " ");
}

/** The sentence under a failed receipt, or null when the receipt's own words are enough. */
export function failureSentence(reason: string | undefined): string | null {
  if (!reason) return null;
  if (reason === "stale_proposal") return "This card is out of date; refresh it.";
  return FAILURE_WORDS[reason] ?? null;
}

/** "Buy 20 AAPL" or "Sell 10 AAPL". */
export function proposalTitle(p: Pick<ValueProposalLike, "kind" | "shares" | "symbol">): string {
  return `${p.kind === "buy" ? "Buy" : "Sell"} ${shareCount(p.shares)} ${p.symbol}`;
}

/** Who proposed it, in words; Claude's number is named as Claude's. */
export function causeWords(p: Pick<ValueProposalLike, "kind" | "cause">): string {
  if (p.cause === "python") return "Python's rules proposed this.";
  if (p.kind === "sell") return "Only Claude's number makes this sale; it waits for your tap.";
  return "Claude's verdict makes this name READY; Python's gates still apply.";
}

/**
 * What a tap on Approve may cause, said before it is made (plan ruling 31). The price is the close
 * the proposal was sized at, never a cap: the limit goes out at the mid of a fresh quote at the
 * next check (final review I-D).
 */
export function approveSentence(p: ValueProposalLike, releaseMaxCloses: number): string {
  const lead = p.cause === "claude" && p.kind === "sell" ? "Only Claude's number makes this sale. " : "";
  const recheck = " The gate checks it again on a fresh quote before anything is sent.";
  if (p.kind === "sell") {
    return `${lead}Approving lets the system sell ${sharesWord(p.shares)} of ${p.symbol} at its next check.${recheck}`;
  }
  const sized = p.price === null || p.price === undefined ? "" : `, sized at the close of ${price(p.price)}`;
  return (
    `Approving lets the system buy ${sharesWord(p.shares)} of ${p.symbol} at its next check${sized}, ` +
    `at the mid of a fresh quote. ` +
    `If cash is short it may close up to ${releaseMaxCloses} of your wheel's cash-secured puts ` +
    `at breakeven or better to fund it.${recheck}`
  );
}

export function rejectSentence(p: ValueProposalLike): string {
  const verb = p.kind === "buy" ? "buy" : "sell";
  return `Rejecting records a no: the system will not ${verb} ${sharesWord(p.shares)} of ${p.symbol} on this proposal.`;
}

/** "expires in 5h", "expires in 40m", "expired". `now` is epoch ms. */
export function expiresWords(expiresAt: string, now: number = Date.now()): string {
  const t = new Date(expiresAt).getTime();
  if (Number.isNaN(t)) return UNKNOWN;
  const mins = Math.floor((t - now) / 60000);
  if (mins <= 0) return "expired";
  if (mins < 60) return `expires in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `expires in ${hrs}h`;
  return `expires in ${Math.floor(hrs / 24)}d`;
}
