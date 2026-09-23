import type { ReactNode } from "react";
import clsx from "clsx";

type Tone = "info" | "positive" | "caution";

// Mirrors the rest of the app's rule that state is never colour alone (see StageBadge,
// CheckRibbon): each tone pairs its colour with a distinct border treatment - a caution
// callout is dashed, not just a different hue - and the label text itself says what kind
// of fact this is, so the tone reads correctly even for a viewer who can't see colour.
const TONE_CLASS: Record<Tone, string> = {
  info: "border-l-4 border-focus",
  positive: "border-l-4 border-gain",
  caution: "border-l-4 border-dashed border-unknown",
};

const TONE_LABEL_CLASS: Record<Tone, string> = {
  info: "text-focus",
  positive: "text-gain",
  caution: "text-unknown",
};

/**
 * A raised-by-lightness callout for facts that are not design choices but hard
 * invariants or notable guarantees - "no LLM can place an order," "paper by default."
 * Elevation (bg-elevated) marks it as load-bearing, per this app's own rule that a
 * surface change is a background change; the tone accent is a second, deliberate layer
 * on top of that, not a replacement for it.
 */
export function Callout({
  label,
  tone = "info",
  children,
}: {
  label: string;
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <div className={clsx("rounded-md bg-elevated px-4 py-3", TONE_CLASS[tone])}>
      <div
        className={clsx(
          "mb-1 font-mono text-[11px] font-medium uppercase tracking-wide",
          TONE_LABEL_CLASS[tone],
        )}
      >
        {label}
      </div>
      <div className="text-sm text-content">{children}</div>
    </div>
  );
}
