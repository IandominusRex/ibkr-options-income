"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import { submitCommand, useCommandStatus, type CommandStatus } from "@/lib/commands";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import { Button } from "@/components/ui/Button";
import type { ControlsResponse } from "@/components/options/types";

/**
 * Asks the news process for a fresh brief on one name: a `news_brief` command, its receipt and its poll
 * (unchanged; restyled in place in web overhaul Part 7 as the secondary button, with a failure said in
 * words, never red). It trades nothing.
 */
export function BriefRequest({ symbol }: { symbol: string }) {
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();
  const controls = useQuery({ queryKey: ["options", "controls"], queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
                              placeholderData: (prev) => prev, refetchInterval: 30_000 });
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") qc.invalidateQueries({ queryKey: ["news", "ticker", symbol] });
  }, [current, qc, symbol]);

  async function onClick() {
    setError(null);
    setSubmitting(true);
    try {
      setCommand(await submitCommand("news_brief", { symbol }));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? "You do not have permission to do this." : "The request could not be created.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <Button variant="secondary" onClick={onClick} disabled={submitting || current?.status === "pending"}>
        Request fresh brief
      </Button>
      {error && <p className="text-sm" role="alert">{error}</p>}
      {current && <CommandReceipt command={current} order={null} drainHealthy={controls.data?.drain_healthy ?? true} plainReasons={["invalid_symbol"]} />}
    </div>
  );
}
