"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import { submitCommand, useCommandStatus, type CommandStatus } from "@/lib/commands";
import type { ControlsResponse } from "@/components/options/types";

/**
 * The `refresh` command's flow, shared by the Portfolio page's Refresh button and the refresh
 * icon on Home and the position pages: one `POST /commands` (kind "refresh", no confirmation: it
 * creates no candidate, approval or order), polled until it is terminal, after which the queries
 * under `scope` are asked for again. "portfolio" is the Portfolio page's own prefix; "all" is every
 * query the page holds, for a page that shows more than the portfolio (a position's chart and
 * headlines, Home's trades and pay).
 *
 * The drain's health comes from `GET /options/controls`, so a refresh sent while `approval_service`
 * is down reads as stalled, in words, instead of queued forever. `drainHealthy` is true while that
 * query loads, so an unloaded drain is never reported dead.
 */
export function useBrokerRefresh(scope: "portfolio" | "all" = "portfolio") {
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls.data?.drain_healthy ?? true;

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  // Once per command id: every GET /commands/{id} body carries a fresh `as_of`, so `current` is a new
  // object on each refetch and keying on it would re-invalidate, and refetch, forever. The command
  // queries are left out of "all" for the same reason (the poll that ended must not be asked again).
  const handled = useRef<number | null>(null);
  useEffect(() => {
    if (!current || current.status === "pending" || handled.current === current.id) return;
    handled.current = current.id;
    qc.invalidateQueries(
      scope === "all"
        ? { predicate: (q) => q.queryKey[0] !== "command" }
        : { queryKey: ["portfolio"] },
    );
  }, [current, qc, scope]);

  const inFlight = submitting || (current != null && current.status === "pending");

  async function refresh() {
    setError(null);
    setSubmitting(true);
    try {
      setCommand(await submitCommand("refresh", {}));
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return { refresh, inFlight, current, error, drainHealthy };
}

function describeError(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) {
    return "You do not have permission to do this. Command not created.";
  }
  return "The command could not be created. Nothing was sent.";
}
