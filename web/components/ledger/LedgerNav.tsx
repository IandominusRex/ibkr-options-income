"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const TABS = [
  { href: "/ledger", label: "Overview" },
  { href: "/ledger/trades", label: "Trades" },
  { href: "/ledger/import", label: "Import" },
];

export function LedgerNav() {
  const path = usePathname();
  return (
    <nav aria-label="Ledger sections" className="flex gap-2 border-b border-border pb-2">
      {TABS.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={path === t.href ? "page" : undefined}
          className={clsx(
            "rounded-md px-3 py-1.5 text-sm",
            path === t.href ? "bg-elevated text-content" : "text-muted hover:text-content",
          )}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
