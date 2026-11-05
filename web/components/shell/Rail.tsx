"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { NAV, activeKey } from "@/lib/nav";
import type { ApprovalListResponse } from "@/components/options/types";
import { BotCard } from "./BotCard";

export function usePendingCount(): number | null {
  // Same key and URL as usePendingApprovals (features/home/NeedsYou.tsx), so react-query dedupes.
  const { data } = useQuery({
    queryKey: ["options", "approvals", "pending"],
    queryFn: () => apiFetch<ApprovalListResponse>("/options/approvals?status=pending"),
    refetchInterval: 30_000,
  });
  return data ? data.approvals.length : null;
}

export function Rail() {
  const pathname = usePathname();
  const current = activeKey(pathname);
  const pending = usePendingCount();

  return (
    <nav aria-label="Sections" className="hidden w-[200px] shrink-0 flex-col bg-surface px-3 py-[18px] md:flex">
      <div className="px-2.5 pb-4 text-[0.9375rem] font-extrabold">IBKR Income</div>
      <ul className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
        {NAV.map((item) => {
          const on = item.key === current;
          const badge = item.key === "trades" && pending !== null && pending > 0 ? pending : null;
          const Icon = item.icon;
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                aria-current={on ? "page" : undefined}
                aria-label={badge !== null ? `${item.label}, ${badge} waiting` : item.label}
                className={clsx(
                  "flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-sm",
                  on ? "bg-sunk font-semibold text-content" : "text-muted hover:text-content",
                )}
              >
                <Icon aria-hidden="true" size={17} strokeWidth={2} />
                <span className="flex-1">{item.label}</span>
                {badge !== null && (
                  <span aria-hidden="true" className="rounded-full bg-primary px-[7px] text-[11px] font-bold text-on-primary">
                    {badge}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
      <BotCard />
    </nav>
  );
}
