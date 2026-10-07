"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { LedgerNav } from "./LedgerNav";
import type { LedgerFeedStatus, LedgerImportsResponse } from "./types";

// Client-side UX hint only; the server enforces ledger.upload_max_bytes (ruling F6).
const MAX_BYTES = 5 * 1024 * 1024;

// FileReader rather than File.text(): same result, and it exists in every browser and in jsdom.
function readText(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error);
    r.readAsText(f);
  });
}

function Feed({ label, s }: { label: string; s: LedgerFeedStatus }) {
  let text = "not set up (see SETUP.md, Trade ledger)";
  if (s.configured) text = s.last_error ? `failing: ${s.last_error}` : s.last_run ? `last run ${s.last_run.slice(0, 16).replace("T", " ")} UTC${s.last_status ? ` (${s.last_status})` : ""}` : "set up, not run yet";
  return <li className="text-sm text-muted">{label}: {text}</li>;
}

export function ImportView() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["ledger", "imports"], queryFn: () => apiFetch<LedgerImportsResponse>("/ledger/imports") });
  const [commandId, setCommandId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  const [reviewId, setReviewId] = useState<{ command: number; action: number } | null>(null);
  const reviewStatus = useCommandStatus(reviewId?.command ?? null);
  const reviewPending = reviewId !== null && !(reviewStatus.data && reviewStatus.data.status !== "pending");

  useEffect(() => {
    const st = status.data;
    if (!st) return;
    if (st.status === "applied") {
      const counts = (st.result?.counts ?? null) as Record<string, number> | null;
      const part = (key: string, label: string) => `${counts && typeof counts[key] === "number" ? counts[key] : "n/a"} ${label}`;
      setMessage(`Imported: ${part("new", "new")}, ${part("duplicate", "already present")}, ${part("superseded", "merged with broker fills")}.`);
      void qc.invalidateQueries({ queryKey: ["ledger"] });
    } else if (st.status === "failed") {
      setMessage(`Import failed: ${String(st.result?.reason ?? "error")}`);
    }
  }, [status.data, qc]);

  useEffect(() => {
    const st = reviewStatus.data;
    if (!st) return;
    if (st.status === "applied") {
      void qc.invalidateQueries({ queryKey: ["ledger"] });
    } else if (st.status === "failed" || st.status === "expired") {
      setMessage(`Could not mark reviewed: ${String(st.result?.reason ?? st.status)}`);
    }
  }, [reviewStatus.data, qc]);

  async function onFile(f: File | undefined) {
    setMessage(null);
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".pdf")) {
      setMessage("PDF statements are not supported. In Client Portal, open the same statement and choose CSV as the format.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setMessage("That file is over 5 MB. Split the period into two statements.");
      return;
    }
    try {
      const content = await readText(f);
      const r = await submitCommand("ledger_import", { filename: f.name, content });
      setCommandId(r.id);
      setMessage("Importing");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function markReviewed(id: number) {
    setMessage(null);
    try {
      const r = await submitCommand("ledger_ca_reviewed", { corporate_action_id: id });
      setReviewId({ command: r.id, action: id });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not mark reviewed");
    }
  }

  return (
    <div className="space-y-6" data-testid="import-view">
      <LedgerNav />
      <section className="space-y-2 rounded-lg bg-surface p-5">
        <h2 className="text-sm text-content">Upload an IBKR Activity Statement</h2>
        <p className="text-xs text-muted">Client Portal, Performance and Reports, Statements, Activity, format CSV. Re-uploading the same file changes nothing.</p>
        <label className="block text-sm text-muted">
          Activity Statement CSV
          <input type="file" accept=".csv,text/csv" aria-label="Activity Statement CSV" onChange={(e) => void onFile(e.target.files?.[0])} className="mt-2 block text-sm text-content" />
        </label>
        {message && <p className="text-sm text-content" role="status">{message}</p>}
      </section>

      {data && (
        <>
          <ul className="space-y-1">
            <Feed label="Flex pull" s={data.flex} />
            <Feed label="Google Sheet mirror" s={data.sheets} />
          </ul>

          {data.corporate_actions.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm text-content">Corporate actions</h2>
              <p className="text-xs text-muted">These are stored but never applied to cost basis automatically. Check each one, then mark it reviewed.</p>
              <ul className="space-y-2 text-sm">
                {data.corporate_actions.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3">
                    <span className="tabular text-muted">{a.event_date}</span>
                    <span className="text-content">{a.description}</span>
                    {a.reviewed ? <span className="text-xs text-muted">reviewed</span> : (
                      <button type="button" disabled={reviewPending} onClick={() => void markReviewed(a.id)} className="rounded bg-elevated px-2 py-0.5 text-xs text-content">{reviewPending && reviewId?.action === a.id ? "Marking" : "Mark reviewed"}</button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-sm text-content">Import history</h2>
            <table className="w-full text-sm">
              <thead className="text-left text-muted"><tr><th className="py-1 pr-4">When</th><th className="py-1 pr-4">Source</th><th className="py-1 pr-4">File</th><th className="py-1 pr-4">Result</th><th className="py-1 pr-4">Counts</th></tr></thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.id} className="border-t border-border align-top">
                    <td className="tabular py-1 pr-4">{r.started_at.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1 pr-4">{r.source}</td>
                    <td className="py-1 pr-4">{r.filename}</td>
                    <td className={`py-1 pr-4 ${r.status === "ok" ? "text-gain" : "text-loss"}`}>{r.status}{r.reason ? ` (${r.reason})` : ""}</td>
                    <td className="tabular py-1 pr-4 text-muted">{Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
