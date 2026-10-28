"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { Sheet } from "@/components/ui/Sheet";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { money, pct } from "./format";
import { OutcomePill } from "./OutcomePill";
import { OUTCOMES, type LedgerTradeResponse } from "./types";

export function TradePanel({ orderKey, onClose }: { orderKey: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["ledger", "trade", orderKey],
    queryFn: () => apiFetch<LedgerTradeResponse>(`/ledger/trades/${orderKey}`),
  });
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [override, setOverride] = useState("");
  const [exclude, setExclude] = useState(false);
  const [commandId, setCommandId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  // Re-sync the form from server data only for a newly selected trade or right after a save
  // was applied, never on a background refetch (that would wipe unsaved edits).
  const syncedKey = useRef<string | null>(null);
  const resync = useRef(false);

  useEffect(() => {
    if (!data) return;
    if (syncedKey.current === orderKey && !resync.current) return;
    syncedKey.current = orderKey;
    resync.current = false;
    setNotes(data.trade.notes);
    setTags(data.trade.tags.join(", "));
    setOverride(data.trade.outcome_overridden ? data.trade.outcome : "");
    setExclude(data.trade.exclude_from_stats);
  }, [data, orderKey]);

  useEffect(() => {
    if (status.data?.status === "applied") resync.current = true;
    if (status.data?.status === "applied") void qc.invalidateQueries({ queryKey: ["ledger"] });
  }, [status.data?.status, qc]);

  async function save() {
    setError(null);
    try {
      const r = await submitCommand("ledger_annotate", {
        order_key: orderKey,
        notes,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        outcome_override: override,
        exclude_from_stats: exclude,
      });
      setCommandId(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    }
  }

  const state = status.data?.status;
  const t = data?.trade;
  return (
    <Sheet open onClose={onClose} title="Trade">
      {!data && <p className="text-sm text-muted">Loading</p>}
      {data && t && (
        <div className="grid gap-5">
          <div className="grid gap-2">
            <p className="font-mono text-sm font-semibold">
              {t.side} {t.lots} x {t.underlying} {t.expiry} {t.strike}
              {t.right}
            </p>
            <p>
              <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
            </p>
            <dl className="tabular border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium">
              {[
                ["Premium", money(t.premium, t.currency)],
                ["Net P&L", money(t.net_pnl, t.currency)],
                ["% Profit (sheet)", pct(t.pct_profit)],
                ["Annualised net", pct(t.annualised_net_pct)],
                ["IBKR realised", money(t.ibkr_realized_pnl, t.currency)],
                ...(t.rolled_from ? [["Rolled from", t.rolled_from]] : []),
                ...(t.rolled_to ? [["Rolled to", t.rolled_to]] : []),
              ].map(([label, value]) => (
                <div key={label} className="flex min-h-6 items-baseline justify-between gap-3">
                  <dt className="min-w-0 font-sans font-normal text-muted">{label}</dt>
                  <dd className={clsx("text-right", value === "n/a" && "hatch text-unknown")}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
          <section className="grid gap-1">
            <h3 className="text-[1.0625rem] font-bold">Executions</h3>
            <ul className="tabular font-mono text-xs text-muted">
              {data.executions.map((e) => (
                <li key={e.id} className="border-t border-border py-1.5 first:border-t-0">
                  {e.trade_time.slice(0, 19).replace("T", " ")} {e.quantity} @ {e.price} {e.codes} ({e.source}
                  {e.superseded_by ? ", superseded" : ""})
                </li>
              ))}
            </ul>
          </section>
          <section className="grid gap-3">
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Notes</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={clsx(FIELD, "w-full py-2")} />
            </label>
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Tags (comma separated)</span>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className={clsx(FIELD, "w-full")} />
            </label>
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Outcome override</span>
              <select value={override} onChange={(e) => setOverride(e.target.value)} className={clsx(FIELD, "w-full")}>
                <option value="">Use computed ({t.computed_outcome})</option>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} className="h-5 w-5" />
              Exclude from win rate and averages (still counted in money totals)
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="secondary" onClick={save}>
                Save
              </Button>
              {state === "pending" && <span className="text-sm text-muted">Saving</span>}
              {state === "applied" && <span className="text-sm text-gain">Saved</span>}
              {state === "failed" && (
                <span className="text-sm text-loss">Not saved: {String(status.data?.result?.reason ?? "error")}</span>
              )}
              {error && <span className="text-sm text-loss">{error}</span>}
            </div>
          </section>
        </div>
      )}
    </Sheet>
  );
}
