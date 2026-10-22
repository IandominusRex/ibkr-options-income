import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import type { ClaudeContext } from "./types";

/** One row per Claude call, its prompt blocks as chips. The chips are list items, not controls. */
export function CallsCard({ ctx }: { ctx: ClaudeContext }) {
  const calls = ctx.calls ?? [];
  return (
    <Card aria-labelledby="calls-title">
      <h2 id="calls-title" className="text-[1.0625rem] font-bold">
        What each Claude call reads
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">The context blocks each call&apos;s prompt carries.</p>
      {calls.length === 0 ? (
        <p className="mt-2 text-sm">No calls are listed.</p>
      ) : (
        <ul className="mt-2">
          {calls.map((c) => (
            <li key={c.kind} className="border-t border-border py-3 first:border-t-0">
              <p className="text-sm font-bold">{c.label}</p>
              <ul aria-label={`${c.label} reads`} className="mt-1.5 flex flex-wrap gap-1.5">
                {c.blocks.map((b) => (
                  <li key={b}>
                    <StatusWord>{b}</StatusWord>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
