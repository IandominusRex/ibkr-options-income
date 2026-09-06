import clsx from "clsx";

type Stage = "generator" | "risk_gate" | "score_floor" | "dedupe" | "top_n" | "passed";

const LABELS: Record<Stage, string> = {
  generator: "Filtered",
  risk_gate: "Gate rejected",
  score_floor: "Below score floor",
  dedupe: "Lost dedupe",
  top_n: "Capped out",
  passed: "Passed",
};

// Stage is never communicated by colour alone: each stage gets a text label plus
// a distinct fill or texture, reusing the check ribbon's visual language.
const STAGE_CLASS: Record<Stage, string> = {
  generator: "bg-surface text-muted",
  risk_gate: "border border-loss text-loss",
  score_floor: "bg-elevated text-content",
  dedupe: "bg-elevated text-muted",
  top_n: "bg-elevated text-muted",
  passed: "bg-gain text-background",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return (
    <span
      className={clsx(
        "inline-block rounded-sm px-2 py-0.5 text-xs",
        STAGE_CLASS[stage],
      )}
    >
      {LABELS[stage]}
    </span>
  );
}