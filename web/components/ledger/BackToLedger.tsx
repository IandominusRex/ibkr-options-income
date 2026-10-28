import { ChevronLeft } from "lucide-react";
import Link from "next/link";

/** Where the ledger's own pages lead back to: the Ledger view on Activity. */
export function BackToLedger() {
  return (
    <Link
      href="/activity?view=ledger"
      aria-label="Back to Activity, Ledger"
      className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
    >
      <ChevronLeft size={16} aria-hidden="true" />
      Activity · Ledger
    </Link>
  );
}
