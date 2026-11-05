import type { Metadata } from "next";
import { ImportView } from "@/components/ledger/ImportView";
import { LedgerShell } from "@/components/ledger/LedgerShell";

export const metadata: Metadata = { title: "Import a statement" };

export default function LedgerImportPage() {
  return (
    <LedgerShell>
      <ImportView />
    </LedgerShell>
  );
}
