import { FactCard } from "@/components/explain/FactCard";
import type { ClaudeReviewPayload } from "./types";

// The five review fields render as five labelled cards, never one paragraph, so the bull
// case, the risk case, and the mechanical notes read as distinct ideas rather than one
// undifferentiated block - the same FactCard/Tag language the System Explanation tab uses
// for its own "what comes back, every time" summary of this exact payload shape (see
// components/explain/ClaudePanel.tsx). A null review renders nothing at all, not "No
// review available" in a box. Since Task 10 a review also carries a plain-English
// `summary` (shown first, as the verdict) and the `evidence` ids it cites.
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
  const summary = review.summary ?? "";
  const evidence = review.evidence ?? [];
  if (present.length === 0 && !summary) return null;

  return (
    <div className="space-y-3">
      {summary && (
        <FactCard
          tag={review.recommendation ? `Verdict: ${review.recommendation}` : "Verdict"}
          tone="neutral"
          title="Summary"
          bodyClass="text-sm text-content"
        >
          {summary}
        </FactCard>
      )}
      {present.length > 0 && (
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
      )}
      {evidence.length > 0 && <EvidenceList ids={evidence} />}
    </div>
  );
}

// The ids the verdict cites. The FACTS and NEWS blocks they point into live only in that
// scan's prompt, not in the stored review, so each id is shown with what kind of source
// it is rather than pretending to link to text the console does not have.
function EvidenceList({ ids }: { ids: string[] }) {
  return (
    <div className="text-xs text-muted">
      <span>Cited: </span>
      <ul className="inline-flex flex-wrap gap-2 align-middle">
        {ids.map((id) => (
          <li key={id} className="rounded border border-border px-1.5 py-0.5">
            <span className="font-mono text-content">{id}</span>{" "}
            <span>{evidenceKind(id)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function evidenceKind(id: string): string {
  if (/^F\d+$/.test(id)) return "computed fact";
  if (/^N\d+$/.test(id)) return "news headline";
  return "source";
}
