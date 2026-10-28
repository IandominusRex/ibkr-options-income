"use client";

import clsx from "clsx";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBrokerRefresh } from "@/components/portfolio/useBrokerRefresh";

const ICON =
  "grid h-11 w-11 shrink-0 place-items-center rounded-full text-muted transition-transform duration-[90ms] " +
  "enabled:hover:bg-sunk enabled:hover:text-content motion-safe:enabled:active:scale-[0.98] disabled:cursor-default md:h-9 md:w-9";

function Icon({ busy, label }: { busy: boolean; label: string }) {
  return (
    <>
      <RefreshCw size={18} strokeWidth={2.25} aria-hidden="true" className={clsx(busy && "motion-safe:animate-spin")} />
      <span className="sr-only">{label}</span>
    </>
  );
}

/** What a refresh that did not land says, in words; a refresh that worked says nothing. */
function problem(
  current: ReturnType<typeof useBrokerRefresh>["current"],
  drainHealthy: boolean,
  error: string | null,
): string | null {
  if (error) return error;
  if (!current) return null;
  if (current.status === "pending") return drainHealthy ? null : "The trading service is not draining commands.";
  if (current.status === "applied") return null;
  const reason = current.result && typeof current.result.reason === "string" ? current.result.reason : null;
  if (reason === "broker_unavailable") return "The broker is not connected. These figures are the last reading.";
  return "The refresh did not go through. These figures are the last reading.";
}

function BrokerRefresh({ label, className }: { label: string; className?: string }) {
  const { refresh, inFlight, current, error, drainHealthy } = useBrokerRefresh("all");
  const said = problem(current, drainHealthy, error);
  return (
    <span className={clsx("inline-flex items-center gap-1", className)}>
      {said && (
        <span role={error ? "alert" : "status"} className="max-w-[16rem] text-right text-[0.8125rem] leading-tight text-muted">
          {said}
        </span>
      )}
      <button type="button" aria-busy={inFlight} disabled={inFlight} title={label} onClick={refresh} className={ICON}>
        <Icon busy={inFlight} label={label} />
      </button>
    </span>
  );
}

function PageRefresh({ label, className }: { label: string; className?: string }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  function refetch() {
    setBusy(true);
    // Every query the page holds is asked for again; it resolves once they have all answered.
    void qc.invalidateQueries().finally(() => setBusy(false));
  }
  return (
    <button type="button" aria-busy={busy} disabled={busy} title={label} onClick={refetch} className={clsx(ICON, className)}>
      <Icon busy={busy} label={label} />
    </button>
  );
}

/**
 * The refresh icon (web/DESIGN.md Components → Refresh): a quiet round button with the circular
 * arrow, 44px on a phone, that spins while it works and asks for the freshest state of the page.
 *
 * - `scope="broker"` (Home, a position's page): sends the `refresh` command, which reads the live
 *   positions and account from the broker and stores one snapshot, then asks for every query on the
 *   page again. If the broker is not connected or the trading service is down it says so beside the
 *   icon, and the page keeps the last reading.
 * - `scope="page"` (Stock, News, Trades, Activity): nothing is sent; every query the page holds is
 *   asked for again.
 *
 * Neither creates a candidate, an approval or an order. The icon is never lime: lime means act, and
 * a refresh decides nothing.
 */
export function RefreshButton({
  scope = "page",
  label = "Refresh",
  className,
}: {
  scope?: "broker" | "page";
  label?: string;
  className?: string;
}) {
  return scope === "broker" ? <BrokerRefresh label={label} className={className} /> : <PageRefresh label={label} className={className} />;
}
