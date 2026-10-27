"use client";

import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Name } from "@/features/claude-context/NamesCard";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";

/**
 * What the news service keeps on one name: Python's health and numbers, Claude's story and summary
 * (each labelled as Claude's), upcoming dates. The same row What Claude knows lists for every name.
 * Silent while loading or if the request fails; it says so when the name has no notes.
 */
export function NameNotes({ symbol }: { symbol: string }) {
  const { data } = useClaudeContext();
  if (!data) return null;
  const sym = symbol.toUpperCase();
  const dossier = (data.dossiers ?? []).find((d) => d.symbol === sym);
  const titleId = `notes-title-${sym}`;
  return (
    <Card aria-labelledby={titleId}>
      <h2 id={titleId} className="text-[1.0625rem] font-bold">
        What the news service keeps on {sym}
      </h2>
      {!data.available ? (
        <p className="mt-2 text-sm">The news service has not written anything yet, so there are no notes.</p>
      ) : dossier ? (
        <ul className="mt-1">
          <Name d={dossier} />
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">
          No notes yet for {sym}. The news service writes them for the names in the book and the universe.
        </p>
      )}
      <Link
        href="/more/claude"
        className="mt-2 inline-flex min-h-11 items-center text-[0.8125rem] font-semibold text-content underline underline-offset-2 md:min-h-8"
      >
        All names and the market picture
      </Link>
    </Card>
  );
}
