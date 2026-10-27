import { percent, shortDay } from "@/features/claude-context/format";
import type { Dossier, RegimeLimit } from "@/features/claude-context/types";
import { shiftDay } from "@/features/trades/time";
import type { components } from "@/lib/api-types";

export type SizingAction = components["schemas"]["SizingActionOut"];

/** What an index's regime does to new puts, in one sentence; null when its limits are not known. */
export function limitSentence(l: RegimeLimit | undefined): string | null {
  if (!l) return null;
  const normal = l.budget_pct >= 100 && l.per_trade_pct >= 100 && (l.max_new_per_day ?? null) === null;
  if (normal) return "New puts at their normal size.";
  const parts = [`${percent(l.budget_pct)} of the normal budget`, `${percent(l.per_trade_pct)} per trade`];
  if (l.max_new_per_day !== null && l.max_new_per_day !== undefined) parts.push(`at most ${l.max_new_per_day} a day`);
  return `New puts: ${parts.join(", ")}.`;
}

/** The status word for a sizing record's kind. */
const KIND_WORD: Record<string, string> = {
  regime_budget: "Regime budget",
  regime_ceiling: "Regime size limit",
  leveraged_ceiling: "Leveraged ETF limit",
  regime_daily_limit: "Daily limit",
  regime_floor_lot: "Guaranteed lot",
  escalation_trim: "Trimmed as the market fell",
  scale_in_zone: "Scale-in ladder",
  loss_exit_cooldown: "Loss-exit cooldown",
  bottoming_lot: "Bottoming lot",
  claude_cut: "Claude's cut",
  claude_cut_unapplied: "Claude's cut, recorded only",
  cc_breakout_floor: "Breakout rule",
};

export function kindWord(kind: string): string {
  return KIND_WORD[kind] ?? kind.replace(/_/g, " ");
}

/** The reason codes the rules write inside a record's reason, in plain words (the API's own list). */
const CODE_WORDS: Record<string, string> = {
  regime_budget: "the market regime has shrunk the put budget",
  regime_ceiling: "over the market regime's size limit",
  leveraged_ceiling: "over the size limit for a leveraged ETF",
  regime_daily_limit: "the market regime's limit on new puts for today is used up",
  scale_in_zone_not_reached: "the price has not reached the next lower entry zone",
  loss_exit_cooldown: "a loss exit on this name earlier today",
  bottoming_delta_too_high: "a bottoming-signal lot must be a lower-delta strike",
  bottoming_lot_recent: "a bottoming-signal lot was already opened on this name lately",
  cc_breakout_strike_floor: "below the strike floor after a breakout",
  cc_breakout_delta: "too close to the money after a breakout",
};

/** "stopped by the scale-in ladder (loss_exit_cooldown, x)" with each known code spelled out. */
export function reasonWords(reason: string): string {
  return reason.replace(/\(([^()]*)\)/, (whole, inner: string) => {
    const codes = inner.split(",").map((c) => c.trim());
    if (!codes.every((c) => /^[a-z0-9_]+$/.test(c))) return whole;
    return `(${codes.map((c) => CODE_WORDS[c] ?? c).join("; ")})`;
  });
}

/** "Held back: 0 of 2 contracts sent." / "Sent 1 of 3 contracts." / "Sent 2 contracts." */
export function sentSentence(a: Pick<SizingAction, "deterministic_contracts" | "sent_contracts">): string {
  const { deterministic_contracts: want, sent_contracts: sent } = a;
  if (sent <= 0) return `Held back: 0 of ${want} contract${want === 1 ? "" : "s"} sent.`;
  if (sent < want) return `Sent ${sent} of ${want} contracts.`;
  return `Sent ${sent} contract${sent === 1 ? "" : "s"}.`;
}

export function actionTitle(a: Pick<SizingAction, "underlying" | "strike" | "right" | "expiry">): string {
  return `${a.underlying} $${a.strike} ${a.right === "C" ? "call" : "put"} · ${shortDay(a.expiry)}`;
}

/** Event dates closer than this many days show as a word on a position row. */
export const EVENT_WITHIN_DAYS = 10;

/** What a position row shows about its name from the dossier: weak health, a near event date. */
export function nameFlags(d: Dossier | undefined, today: string): { weak: boolean; event: string | null } {
  if (!d) return { weak: false, event: null };
  const limit = shiftDay(today, EVENT_WITHIN_DAYS);
  const dates = (d.events ?? []).map((e) => e.on).filter((on) => on >= today && on <= limit).sort();
  return { weak: d.health === "weak", event: dates[0] ?? null };
}
