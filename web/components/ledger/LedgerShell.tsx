import type { ReactNode } from "react";

/** The page frame of the ledger's own routes (`/ledger/trades`, `/ledger/ticker/:symbol`, `/ledger/import`). */
export function LedgerShell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6">{children}</div>;
}
