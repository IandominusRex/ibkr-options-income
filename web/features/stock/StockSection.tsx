import type { ReactNode } from "react";
import { Card } from "@/components/ui/Card";

export type SectionState = "ready" | "pending" | "unavailable";

/**
 * One section of the stock page as a white card (web overhaul Part 5): its title, then the content
 * once it is ready, or one sentence saying it is still being built or why it is not available. The
 * reason comes from the API and is shown as written (`Section.reason`, src/api/models/research.py).
 */
export function StockSection({
  id,
  title,
  state,
  reason,
  children,
}: {
  id: string;
  title: string;
  state: SectionState;
  reason?: string | null;
  children?: ReactNode;
}) {
  const titleId = `stock-${id}-title`;
  return (
    <Card aria-labelledby={titleId}>
      <h2 id={titleId} className="text-[1.0625rem] font-bold">
        {title}
      </h2>
      <div className="mt-2">
        {state === "ready" ? (
          children
        ) : state === "pending" ? (
          <p role="status" className="text-sm text-muted">
            {reason ?? "Building this section. It will appear shortly."}
          </p>
        ) : (
          <p className="text-sm text-muted">{reason ?? "Not available for this symbol."}</p>
        )}
      </div>
    </Card>
  );
}
