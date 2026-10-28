import { ImportView } from "@/components/ledger/ImportView";
import { LedgerShell } from "@/components/ledger/LedgerShell";

export default function LedgerImportPage() {
  return (
    <LedgerShell>
      <ImportView />
    </LedgerShell>
  );
}
