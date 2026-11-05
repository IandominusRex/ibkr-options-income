"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import {
  loadPersistedCommand,
  savePersistedCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";

/**
 * "Run Claude's analysis": one click queues a Claude read of this name (`value_analyse`). There is
 * no confirmation step because the command changes no order state and moves no money: it asks the
 * value process to read the filings and write notes, within Part 4's daily caps. A receipt follows
 * the command. The in-flight command survives a reload under `value-analyse:<SYMBOL>`.
 *
 * This is the only place in the stock page that sends a command; the label names the act and
 * carries none of Claude's text.
 */
export function AnalyseButton({ symbol, onQueued }: { symbol: string; onQueued?: () => void }) {
  const subject = `value-analyse:${symbol}`;
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();
  const queued = useRef(false);

  // A reload while a read was pending: pick the command back up.
  useEffect(() => {
    const persisted = loadPersistedCommand(subject);
    if (persisted) setCommand(persisted);
    // Mount-only, as in the decide controls: the subject never changes under one instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const query = useCommandStatus(command?.id ?? null);
  const current = (query.data ?? command) as CommandStatus | null;

  useEffect(() => {
    savePersistedCommand(subject, current && current.status === "pending" ? current : null);
  }, [subject, current]);

  useEffect(() => {
    if (!current || current.status === "pending") return;
    qc.invalidateQueries({ queryKey: ["value", "ticker", symbol] });
    if (current.status === "applied" && !queued.current) {
      queued.current = true;
      onQueued?.();
    }
  }, [current, qc, symbol, onQueued]);

  async function run() {
    setError(null);
    setSubmitting(true);
    queued.current = false;
    try {
      setCommand(await submitCommand("value_analyse", { symbol }));
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? "You do not have permission to do this. Nothing was queued."
          : "The request could not be made. Nothing was queued.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const inFlight = submitting || (current != null && current.status === "pending");
  const reason = (current?.result as { reason?: string } | null)?.reason;
  const off = current?.status === "failed" && reason === "claude_off";

  return (
    <div>
      <Button variant="secondary" disabled={inFlight} onClick={run}>
        Run Claude&apos;s analysis
      </Button>
      {error && (
        <p className="mt-2 text-xs text-loss" role="alert">
          {error}
        </p>
      )}
      {current && <CommandReceipt command={current} order={null} drainHealthy plainReasons={["claude_off"]} />}
      {off && <p className="mt-2 text-sm">Claude&apos;s reads are off in config.</p>}
      {current?.status === "applied" && (
        <p className="mt-2 text-sm">
          Claude&apos;s read is queued. The value process runs it when it can, within its daily limits, and this block
          looks again every few seconds for ten minutes.
        </p>
      )}
    </div>
  );
}
