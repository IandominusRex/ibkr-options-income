import type { ClaudeReviewPayload } from "./types";

// The five review fields render as five labelled sections, never one paragraph.
// A null review renders nothing at all, not "No review available" in a box.
export function ReviewPanel({ review }: { review: ClaudeReviewPayload | null }) {
  if (!review) return null;
  const sections: { label: string; text: string }[] = [
    { label: "Why attractive", text: review.why_attractive },
    { label: "Risks", text: review.risks },
    { label: "Tradeoffs", text: review.tradeoffs },
    { label: "Assignment considerations", text: review.assignment_considerations },
    { label: "Rolling considerations", text: review.rolling_considerations },
  ];
  return (
    <div className="space-y-4">
      {sections.map(
        (s) =>
          s.text && (
            <section key={s.label}>
              <h3 className="text-xs font-medium tracking-wide text-muted">{s.label}</h3>
              <p className="mt-1 text-sm text-content">{s.text}</p>
            </section>
          ),
      )}
    </div>
  );
}