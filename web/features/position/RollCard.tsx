"use client";

import { useQuery } from "@tanstack/react-query";
import { RollDialogs, RollReceipt, useRollProposal } from "@/components/options/RollProposal";
import type { ShortListResponse } from "@/components/options/types";
import { useControls } from "@/components/shell/BotCard";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";

/**
 * Roll a held short option: the alerts the monitor fired on this contract, then Propose a roll,
 * which raises a roll for approval through the same confirm-then-receipt flow the Shorts table
 * ran (useRollProposal). Secondary, not lime: it proposes, it never trades.
 */
export function RollCard({
  underlying,
  symbol,
  strike,
  right,
}: {
  underlying: string;
  /** The OCC symbol: the roll_request payload and the alerts' key. */
  symbol: string;
  strike: number;
  right: "C" | "P";
}) {
  // Same key as Home's Roll alert word: one request.
  const shorts = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    refetchInterval: 60_000,
  });
  const controls = useControls();
  const roll = useRollProposal(symbol);
  const alerts = shorts.data?.shorts.find((s) => s.position_symbol === symbol)?.alerts ?? [];

  return (
    <Card as="section" aria-labelledby="roll-title">
      <h2 id="roll-title" className="text-[1.0625rem] font-bold">
        Roll
      </h2>
      {shorts.isError && !shorts.data ? (
        <p className="mt-1 text-[0.8125rem] text-muted">Roll alerts could not be loaded right now.</p>
      ) : !shorts.data ? null : alerts.length === 0 ? (
        <p className="mt-1 text-[0.8125rem] text-muted">No roll alert has fired on this contract.</p>
      ) : (
        <ul className="mt-2 grid gap-3">
          {alerts.map((a) => (
            <li key={a.id} className="text-[0.8125rem]">
              <p className="flex flex-wrap items-center gap-2">
                <StatusWord tone="flag">{a.trigger_label}</StatusWord>
                <span className="text-muted">{relativeAge(a.created_at)}</span>
              </p>
              {a.detail && <p className="mt-1">{a.detail}</p>}
              {a.claude_recommendation && (
                <p className="mt-1 text-muted">
                  <span className="font-semibold">Claude&apos;s view:</span> {a.claude_recommendation}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[0.8125rem] text-muted">
        Proposing a roll prices one now and raises it for your approval. Nothing trades until you approve it.
      </p>
      <Button variant="secondary" block className="mt-3" disabled={roll.inFlight} onClick={roll.openConfirm}>
        Propose a roll
      </Button>
      <RollReceipt roll={roll} drainHealthy={controls.data?.drain_healthy ?? true} />
      <RollDialogs roll={roll} contract={{ underlying, strike, right }} />
    </Card>
  );
}
