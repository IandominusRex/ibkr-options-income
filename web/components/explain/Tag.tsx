import clsx from "clsx";

type Tone = "info" | "positive" | "caution" | "neutral";

const TONE_CLASS: Record<Tone, string> = {
  info: "text-focus",
  positive: "text-gain",
  caution: "text-unknown",
  neutral: "text-muted",
};

/** The small uppercase mono eyebrow on a <FactCard/> - a card's category at a glance. */
export function Tag({ tone = "neutral", children }: { tone?: Tone; children: string }) {
  return (
    <div className={clsx("font-mono text-[11px] font-medium uppercase tracking-wide", TONE_CLASS[tone])}>
      {children}
    </div>
  );
}
