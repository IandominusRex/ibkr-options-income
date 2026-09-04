"use client";

import { useState } from "react";
import { CheckRibbon } from "./CheckRibbon";
import { CheckRow, type CheckRowState } from "./CheckRow";

type CheckResultData = {
  id: string;
  category: string;
  statement: string;
  state: CheckRowState;
  actual: number | null;
  threshold: number | number[] | null;
  note: string | null;
};

type CategoryPayload = {
  category: string;
  passed: number;
  failed: number;
  unknown: number;
  evaluable: number;
  total: number;
  not_applicable: boolean;
  note: string | null;
  checks: CheckResultData[];
};

type WarningItem = {
  level: "info" | "caution";
  title: string;
  detail: string;
};

export type ChecksPayloadData = {
  categories: CategoryPayload[];
  warnings: WarningItem[];
};

const CATEGORY_LABEL: Record<string, string> = {
  value: "Value",
  growth: "Growth",
  past: "Past performance",
  health: "Financial health",
  dividend: "Dividend and buybacks",
  fund: "Fund",
  options: "Options income",
};

export function ChecksSection({ data }: { data: ChecksPayloadData }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      {data.warnings.length > 0 && (
        <div className="space-y-2">
          {data.warnings.map((w, i) => (
            <div
              key={i}
              data-testid="warning"
              className="rounded-md border border-loss/40 bg-surface px-4 py-3 text-sm"
            >
              <p className="font-medium text-content">{w.title}</p>
              <p className="mt-1 text-muted">{w.detail}</p>
            </div>
          ))}
        </div>
      )}

      <div className="divide-y divide-border rounded-md border border-border">
        {data.categories.map((cat) => {
          const isOpen = expanded === cat.category && !cat.not_applicable;
          return (
            <div key={cat.category}>
              <button
                type="button"
                aria-expanded={cat.not_applicable ? undefined : isOpen}
                disabled={cat.not_applicable}
                onClick={() =>
                  setExpanded((current) => (current === cat.category ? null : cat.category))
                }
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left disabled:cursor-default"
              >
                <span className="text-sm text-content">
                  {CATEGORY_LABEL[cat.category] ?? cat.category}
                </span>
                <CheckRibbon
                  category={cat.category}
                  passed={cat.passed}
                  failed={cat.failed}
                  unknown={cat.unknown}
                  total={cat.total}
                  notApplicable={cat.not_applicable}
                />
              </button>
              {cat.not_applicable && cat.note && (
                <p className="px-4 pb-3 text-xs text-muted">{cat.note}</p>
              )}
              {isOpen && (
                <div className="border-t border-border px-4 pb-3">
                  {cat.checks.map((chk) => (
                    <CheckRow
                      key={chk.id}
                      statement={chk.statement}
                      state={chk.state}
                      actual={chk.actual}
                      threshold={chk.threshold}
                      note={chk.note}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
