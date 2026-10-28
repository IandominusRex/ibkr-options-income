import { LedgerShell } from "@/components/ledger/LedgerShell";
import { TradesView } from "@/components/ledger/TradesView";

export default function LedgerTradesPage() {
  return (
    <LedgerShell>
      <TradesView />
    </LedgerShell>
  );
}
