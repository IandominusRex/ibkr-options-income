import type { Verdict } from "./types";
import { VERDICT_LABEL } from "./format";

const ICON: Record<Verdict, string> = {
  further_downside_likely: "▼", further_upside_likely: "▲", overreaction_likely: "↺", priced_in: "=", unclear: "?",
};
const TONE: Record<Verdict, string> = {
  further_downside_likely: "text-loss", further_upside_likely: "text-gain", overreaction_likely: "text-content",
  priced_in: "text-muted", unclear: "text-unknown",
};

export function VerdictPill({ verdict, confidence }: { verdict: Verdict; confidence?: string }) {
  return (
    <span data-testid="verdict" className={`inline-flex items-center gap-1 rounded-sm bg-elevated px-2 py-0.5 text-xs ${TONE[verdict]}`}>
      <span aria-hidden="true">{ICON[verdict]}</span>
      {VERDICT_LABEL[verdict]}
      {confidence ? <span className="text-muted"> · {confidence}</span> : null}
    </span>
  );
}
