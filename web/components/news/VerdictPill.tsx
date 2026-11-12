import type { Verdict } from "./types";
import { VERDICT_LABEL } from "./format";

const ICON: Record<Verdict, string> = {
  further_downside_likely: "▼", further_upside_likely: "▲", overreaction_likely: "↺", priced_in: "=", unclear: "?",
};

/**
 * The news model's verdict as an outlined pill (restyled in place, web overhaul Part 7): the icon and the
 * words carry the direction, in ink. A verdict is a forecast, not money, so it is never green or red
 * (web/DESIGN.md Colors); "Unclear" alone is muted.
 */
export function VerdictPill({ verdict, confidence }: { verdict: Verdict; confidence?: string }) {
  return (
    <span
      data-testid="verdict"
      className={`inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs font-semibold ${
        verdict === "unclear" ? "text-muted" : "text-content"
      }`}
    >
      <span aria-hidden="true">{ICON[verdict]}</span>
      {VERDICT_LABEL[verdict]}
      {confidence ? <span className="font-normal text-muted"> · {confidence} confidence</span> : null}
    </span>
  );
}
