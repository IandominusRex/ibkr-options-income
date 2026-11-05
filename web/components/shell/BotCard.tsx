"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import type { ControlsResponse } from "@/components/options/types";
import { BotSheet } from "./BotSheet";

export function useControls() {
  // Same key as AssessedBrowser, ApprovalDetail and useBrokerRefresh: one request for the whole page.
  return useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    refetchInterval: 30_000,
  });
}

export function BotCard() {
  const { data, isError } = useControls();
  const [open, setOpen] = useState(false);

  if (isError && !data) {
    return <p className="rounded-xl bg-sunk p-2.5 text-[0.8125rem] text-muted">Bot status unavailable</p>;
  }
  if (!data) {
    // Holds the card's place (rail foot, More) so nothing jumps when the controls answer.
    return <div role="status" aria-busy="true" aria-label="Loading bot status" className="h-[59px] rounded-xl bg-sunk" />;
  }

  // "Wheel halted": the web halt is the wheel's switch; credit spreads have their own.
  const state = `${data.halted ? "Wheel halted" : "Bot running"} · ${data.mode}`;
  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className="w-full rounded-xl bg-sunk p-2.5 text-left text-[0.8125rem] hover:bg-sunk-deep"
      >
        <span className="block font-bold text-content">{state}</span>
        <span className="block text-muted">{data.autonomy.label}</span>
        {!data.drain_healthy && (
          <span className="mt-1 block font-semibold text-on-flag">The trading service is not draining commands</span>
        )}
      </button>
      <BotSheet open={open} onClose={() => setOpen(false)} controls={data} />
    </>
  );
}
