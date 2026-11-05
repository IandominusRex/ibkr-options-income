import type { ReactNode } from "react";
import type { Segment } from "./types";

/** An unknown figure: hatched `n/a`, never a zero and never a blank. */
export function Hatched({ children = "n/a" }: { children?: ReactNode }) {
  return <span className="hatch px-1 text-unknown">{children}</span>;
}

/**
 * A line made of pieces joined with a middle dot. When every piece is known it is one plain string;
 * an unknown piece keeps its label and draws its trailing "n/a" hatched.
 */
export function Segments({ parts }: { parts: Segment[] }) {
  if (parts.every((p) => !p.unknown)) return <>{parts.map((p) => p.text).join(" · ")}</>;
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p.unknown && p.text.endsWith("n/a") ? (
            <>
              {p.text.slice(0, -3)}
              <Hatched>n/a</Hatched>
            </>
          ) : (
            p.text
          )}
        </span>
      ))}
    </>
  );
}

/** A sub-heading inside the block: small, muted, in the same face as the Home card's. */
export function Subhead({ children }: { children: ReactNode }) {
  return <h4 className="text-xs font-semibold tracking-[0.04em] text-muted">{children}</h4>;
}

/** The label that says a piece of text is Claude's, with the note beside it (a date, a source). */
export function ClaudeLabel({ label, note }: { label: string; note?: string }) {
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
      <span className="font-semibold text-content">{label}</span>
      {note && <span className="text-muted">{note}</span>}
    </p>
  );
}
