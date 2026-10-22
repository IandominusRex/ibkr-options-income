"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { etLabel, signedPercent } from "./format";
import type { ClaudeContext, Dropped } from "./types";

const FIRST = 5;

function Row({ d }: { d: Dropped }) {
  return (
    <li className="border-t border-border py-3 first:border-t-0">
      <p className="break-words text-sm font-semibold">{d.headline}</p>
      <p className="mt-0.5 break-words text-[0.8125rem] text-muted">
        Claude&apos;s reason: {d.reason ? d.reason : <span className="hatch px-1.5 text-unknown">n/a</span>}
      </p>
      <p className="mt-0.5 text-[0.8125rem] text-muted">Judged {etLabel(d.judged_at)}</p>
      {d.promoted && (
        <p className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Promoted</StatusWord>
          <span>
            {d.promoted_move_pct === null
              ? "The market reaction check brought it back."
              : `The market moved ${signedPercent(d.promoted_move_pct)} after it.`}
          </span>
        </p>
      )}
    </li>
  );
}

/** The stories triage kept out of the picture in the last seven days, with Claude's reasons. */
export function DroppedCard({ ctx }: { ctx: ClaudeContext }) {
  const [all, setAll] = useState(false);
  const rows = ctx.dropped ?? [];
  const shown = all ? rows : rows.slice(0, FIRST);
  const unreviewed = ctx.not_reviewed_7d;
  return (
    <Card aria-labelledby="dropped-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="dropped-title" className="text-[1.0625rem] font-bold">
          Dropped as noise
        </h2>
        <span className="text-[0.8125rem] text-muted">Last 7 days</span>
      </div>
      {!ctx.available ? (
        <p className="mt-2 text-sm">The news service has not written anything yet, so no stories have been judged.</p>
      ) : (
        <>
          <p className="mt-1 text-[0.8125rem] text-muted">
            Claude judged these stories not worth putting in the picture. The reasons are Claude&apos;s.
          </p>
          {rows.length === 0 ? (
            <p className="mt-2 text-sm">Nothing was dropped in the last 7 days.</p>
          ) : (
            <ul className="mt-2">
              {shown.map((d) => (
                <Row key={d.cluster_id} d={d} />
              ))}
            </ul>
          )}
          {rows.length > FIRST && !all && (
            <div className="mt-2">
              <Button variant="secondary" onClick={() => setAll(true)}>
                Show all {rows.length}
              </Button>
            </div>
          )}
          {ctx.dropped_total > rows.length && (
            <p className="mt-2 text-[0.8125rem] text-muted">
              Showing the latest {rows.length} of {ctx.dropped_total}.
            </p>
          )}
          {unreviewed > 0 && (
            <p className="mt-2 text-sm">
              {unreviewed} {unreviewed === 1 ? "story was" : "stories were"} not reviewed:{" "}
              {unreviewed === 1 ? "it fell" : "they fell"} outside the batch Claude judged.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
