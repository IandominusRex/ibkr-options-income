"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import type { StrategyFilter } from "@/lib/strategy";
import { actionTitle, kindWord, reasonWords, sentSentence } from "./market";

type Sizing = components["schemas"]["SizingActionsResponse"];

const CLAUDE_CUT = new Set(["claude_cut", "claude_cut_unapplied"]);

/**
 * The day's sizing record on Trades History: puts the market regime, the scale-in ladder, the
 * leveraged-ETF limit or Claude's cut trimmed or held back, so the operator can see why a put the
 * scan found did not trade, or traded smaller. Read-only; nothing here sizes or sends anything.
 * Renders nothing when the day has none.
 */
export function HeldBack({ day, strategy, isToday }: { day: string; strategy: StrategyFilter; isToday: boolean }) {
  const q = useQuery({
    queryKey: ["claude", "sizing", day],
    queryFn: () => apiFetch<Sizing>(`/claude/sizing?day=${day}`),
    refetchInterval: isToday ? 60_000 : false,
  });
  const rows = (q.data?.actions ?? []).filter(
    (a) => strategy === "all" || (strategy === "csp" && a.right === "P") || (strategy === "cc" && a.right === "C"),
  );
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="held-back-title">
      <h2 id="held-back-title" className="mb-2.5 text-[0.8125rem] font-semibold text-muted">
        Held back or trimmed
      </h2>
      <Card as="div">
        <ul>
          {rows.map((a) => (
            <li key={a.id} className="border-t border-border py-[11px] text-sm first:border-t-0 first:pt-0 last:pb-0">
              <span className="font-bold">{actionTitle(a)}</span>
              <span className="ml-1.5 align-[1px]">
                <StatusWord tone={CLAUDE_CUT.has(a.kind) ? "flag" : "neutral"}>{kindWord(a.kind)}</StatusWord>
              </span>
              <div className="text-[0.8125rem] text-muted">
                {sentSentence(a)} {a.regime !== "normal" && `The market was ${a.regime}. `}
              </div>
              <div className="break-words text-[0.8125rem] text-muted">
                {CLAUDE_CUT.has(a.kind) && <span className="mr-1.5 text-xs font-semibold tracking-[0.04em]">Recorded reason, with Claude&apos;s words</span>}
                {reasonWords(a.reason)}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[0.8125rem] text-muted">
          Recorded by the sizing rules. Each is a decision Python made; a cut by Claude can only lower a size.
        </p>
      </Card>
    </section>
  );
}
