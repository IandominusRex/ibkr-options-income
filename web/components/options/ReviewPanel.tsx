import { FactCard } from "@/components/explain/FactCard";
import type { ClaudeReviewPayload } from "./types";

// The five review fields render as five labelled cards, never one paragraph, so the bull
// case, the risk case, and the mechanical notes read as distinct ideas rather than one
// undifferentiated block - the same FactCard/Tag language the System Explanation tab uses
// for its own "what comes back, every time" summary of this exact payload shape (see
// components/explain/ClaudePanel.tsx). A null review renders nothing at all, not "No
// review available" in a box.
export function ReviewPanel({ review }: { review: ClaudeReviewPayload | null }) {
  if (!review) return null;
  const sections: {
    label: string;
    tag: string;
    tone: "info" | "positive" | "caution" | "neutral";
    text: string;
  }[] = [
    { label: "Why attractive", tag: "Bull case", tone: "positive", text: review.why_attractive },
    { label: "Risks", tag: "Bear case", tone: "caution", text: review.risks },
    { label: "Tradeoffs", tag: "Balance", tone: "neutral", text: review.tradeoffs },
    {
      label: "Assignment considerations",
      tag: "Watch for",
      tone: "caution",
      text: review.assignment_considerations,
    },
    {
      label: "Rolling considerations",
      tag: "If challenged",
      tone: "info",
      text: review.rolling_considerations,
    },
  ];
  const present = sections.filter((s) => s.text);
  if (present.length === 0) return null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {present.map((s) => (
        <FactCard
          key={s.label}
          tag={s.tag}
          tone={s.tone}
          title={s.label}
          bodyClass="text-sm text-content"
        >
          {s.text}
        </FactCard>
      ))}
    </div>
  );
}
