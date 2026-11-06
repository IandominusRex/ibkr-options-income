"use client";

import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { StatusWord } from "@/components/ui/StatusWord";
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
            <div key={i} data-testid="warning" className="rounded-xl bg-sunk px-3 py-2.5 text-sm">
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusWord tone={w.level === "caution" ? "flag" : "neutral"}>
                  {w.level === "caution" ? "Caution" : "Note"}
                </StatusWord>
                <span className="font-semibold">{w.title}</span>
              </p>
              <p className="mt-1 text-[0.8125rem] text-muted">{w.detail}</p>
            </div>
          ))}
        </div>
      )}

      <div className="divide-y divide-border">
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
                className="flex min-h-11 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-left disabled:cursor-default"
              >
                <span className="text-sm font-semibold">{CATEGORY_LABEL[cat.category] ?? cat.category}</span>
                <span className="flex items-center gap-2.5">
                  <CheckRibbon
                    category={cat.category}
                    passed={cat.passed}
                    failed={cat.failed}
                    unknown={cat.unknown}
                    total={cat.total}
                    notApplicable={cat.not_applicable}
                  />
                  {!cat.not_applicable && (
                    <span
                      aria-hidden="true"
                      className={clsx(
                        "grid h-[22px] w-[22px] flex-none place-items-center rounded-full bg-sunk",
                        "transition-transform duration-[180ms] ease-out motion-reduce:transition-none",
                        isOpen && "rotate-180",
                      )}
                    >
                      <ChevronDown size={14} strokeWidth={2.25} />
                    </span>
                  )}
                </span>
              </button>
              {cat.not_applicable && cat.note && <p className="pb-2.5 text-[0.8125rem] text-muted">{cat.note}</p>}
              {isOpen && (
                <div className="pb-2.5">
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
