"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  return (
    <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-md space-y-4 overflow-y-auto bg-surface p-5 shadow-lg" aria-label="Trade detail">
      <div className="flex items-start justify-between">
        <h2 className="text-base text-content">Trade</h2>
        <button type="button" onClick={onClose} className="text-sm text-muted hover:text-content">Close</button>
      </div>
      {!data && <p className="text-sm text-muted">Loading</p>}
      {data && (
        <>
          <div className="space-y-1 text-sm">
            <div className="font-mono text-content">
              {data.trade.side} {data.trade.lots} x {data.trade.underlying} {data.trade.expiry} {data.trade.strike}{data.trade.right}
            </div>
            <OutcomePill outcome={data.trade.outcome} overridden={data.trade.outcome_overridden} />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 pt-2 text-muted">
              <dt>Premium</dt><dd className="tabular text-content">{money(data.trade.premium, data.trade.currency)}</dd>
              <dt>Net P&L</dt><dd className="tabular text-content">{money(data.trade.net_pnl, data.trade.currency)}</dd>
              <dt>% Profit (sheet)</dt><dd className="tabular text-content">{pct(data.trade.pct_profit)}</dd>
              <dt>Annualised net</dt><dd className="tabular text-content">{pct(data.trade.annualised_net_pct)}</dd>
              <dt>IBKR realised</dt><dd className="tabular text-content">{money(data.trade.ibkr_realized_pnl, data.trade.currency)}</dd>
              {data.trade.rolled_from && (<><dt>Rolled from</dt><dd className="font-mono text-content">{data.trade.rolled_from}</dd></>)}
              {data.trade.rolled_to && (<><dt>Rolled to</dt><dd className="font-mono text-content">{data.trade.rolled_to}</dd></>)}
            </dl>
          </div>
          <section className="space-y-1">
            <h3 className="text-sm text-content">Executions</h3>
            <ul className="space-y-1 text-xs text-muted">
              {data.executions.map((e) => (
                <li key={e.id} className="tabular">
                  {e.trade_time.slice(0, 19).replace("T", " ")} {e.quantity} @ {e.price} {e.codes} ({e.source}
                  {e.superseded_by ? ", superseded" : ""})
                </li>
              ))}
            </ul>
          </section>
          <section className="space-y-3">
            <label className="block text-sm">
              <span className="text-muted">Notes</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="mt-1 w-full rounded bg-elevated p-2 text-content" />
            </label>
            <label className="block text-sm">
              <span className="text-muted">Tags (comma separated)</span>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className="mt-1 w-full rounded bg-elevated p-2 text-content" />
            </label>
            <label className="block text-sm">
              <span className="text-muted">Outcome override</span>
              <select value={override} onChange={(e) => setOverride(e.target.value)} className="mt-1 w-full rounded bg-elevated p-2 text-content">
                <option value="">Use computed ({data.trade.computed_outcome})</option>
                {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
              Exclude from win rate and averages (still counted in money totals)
            </label>
            <div className="flex items-center gap-3">
              <button type="button" onClick={save} className="rounded-md bg-elevated px-3 py-1.5 text-sm text-content hover:bg-focus/20">Save</button>
              {state === "pending" && <span className="text-sm text-muted">Saving</span>}
              {state === "applied" && <span className="text-sm text-gain">Saved</span>}
              {state === "failed" && <span className="text-sm text-loss">Not saved: {String(status.data?.result?.reason ?? "error")}</span>}
              {error && <span className="text-sm text-loss">{error}</span>}
            </div>
          </section>
        </>
      )}
    </aside>
  );
}
