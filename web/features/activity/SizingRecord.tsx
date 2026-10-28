"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { cutSentence } from "@/features/claude-context/format";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { groupNote, groupSub, groupTitle, marks, rulesNote, signedMark } from "./sizing";
import type { SizingGroup, SizingRecordResponse } from "./types";

function Mark({ label, value }: { label: string; value: number | null }) {
  // No gain or loss colour: a positive number here is usually what an action COST (what a guaranteed
  // lot EARNED, for that one kind), so green would mislead either way.
  return (
    <div>
      <span className={clsx(value === null && "hatch text-unknown")}>{value === null ? UNKNOWN : signedMark(value)}</span>{" "}
      <span className="font-sans text-xs font-normal text-muted">{label}</span>
    </div>
  );
}

function Line({ g }: { g: SizingGroup }) {
  const m = marks(g);
  const notes = [groupNote(g), rulesNote(g)].filter((n): n is string => n !== null);
  return (
    <li className="border-t border-border py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <span className="font-bold">{groupTitle(g)}</span>
          <div className="text-[0.8125rem] text-muted">{groupSub(g)}</div>
          {notes.map((n) => (
            <p key={n} className="mt-0.5 text-[0.8125rem] text-muted">
              {n}
            </p>
          ))}
        </div>
        {g.split !== "pushed_out" && (
          <div className="tabular shrink-0 text-right font-mono font-semibold">
            <Mark label="to expiry" value={m.expiry} />
            <Mark label="exit rules" value={m.rules} />
          </div>
        )}
      </div>
    </li>
  );
}

/**
 * The sizing record: what the market-regime limits, the scale-in ladder, the leveraged-ETF
 * ceiling, the guaranteed lots and Claude's size cut held back or changed, and what that would have
 * earned, valued so far. It is the review the live-cutover gate asks for. Display only: nothing
 * here can change a limit, a size or a weight. Rows not yet valued are counted and never valued.
 */
export function SizingRecord({ since }: { since?: string }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "sizing", since ?? null],
    queryFn: () => apiFetch<SizingRecordResponse>(`/pnl/sizing${since ? `?since=${since}` : ""}`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
  const ctx = useClaudeContext().data;

  return (
    <Card aria-labelledby="sizing-title">
      <h2 id="sizing-title" className="text-[1.0625rem] font-bold">
        Sizing record
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">
        What the market-regime limits, the scale-in ladder, the leveraged-ETF ceiling, the guaranteed lots and
        Claude&apos;s size cut held back or changed, and what that would have earned. A positive number is what the
        held-back contracts would have earned: the action cost that much. A negative number is a loss it avoided. For
        guaranteed lots the contracts counted are the ones the floor let through, so a positive number is what they
        earned. This is the review the live cutover asks for before Claude&apos;s cut applies in live trading.
      </p>
      {ctx?.available && (
        <p className="mt-2 text-sm">
          {cutSentence(ctx.claude_cut_mode, ctx.account_mode, ctx.claude_cut_breaker_tripped_today)}
        </p>
      )}
      <div className="mt-2">
        {isError && !data ? (
          <>
            <p className="text-sm text-muted">Could not load the sizing record.</p>
            <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
          </>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the sizing record" className="h-24 rounded-xl bg-sunk" />
        ) : data.groups.length === 0 ? (
          <p className="py-2 text-sm text-muted">
            {since ? `No sizing actions on record since ${since}.` : "No sizing actions on record yet."}
          </p>
        ) : (
          <ul>
            {data.groups.map((g) => (
              <Line key={g.key} g={g} />
            ))}
          </ul>
        )}
      </div>
      <p className="mt-3 text-[0.8125rem] text-muted">
        Rows not yet valued are counted and wait for their expiry. &quot;To expiry&quot; marks each option a line
        counts at its expiry close. &quot;Exit rules&quot; walks the daily closes and exits at the system&apos;s own
        profit-take line (and, for a leveraged ETF, its loss line).
      </p>
    </Card>
  );
}
