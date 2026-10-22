"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { CallsCard } from "./CallsCard";
import { DroppedCard } from "./DroppedCard";
import { NamesCard } from "./NamesCard";
import { PictureCard } from "./PictureCard";
import { RegimeCard } from "./RegimeCard";
import type { ClaudeContext } from "./types";

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-[720px] px-4 py-3 md:px-7 md:py-4">
      <Link
        href="/more"
        className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
      >
        <ChevronLeft size={16} aria-hidden="true" />
        More
      </Link>
      <h1 className="mt-2 text-2xl font-extrabold tracking-[-0.015em]">What Claude knows</h1>
      <p className="mt-1 text-sm text-muted">
        The market picture Claude reads, the limits the system puts on new puts, and what each Claude call is given.
        Read-only: nothing here changes a limit, a size or an order.
      </p>
      <div className="mt-5 grid gap-4">{children}</div>
    </div>
  );
}

/** A labelled block in the shape of the first card while the request is out. */
function Loading() {
  return (
    <div role="status" aria-label="Loading what Claude knows" aria-busy="true">
      <Card as="div" className="grid gap-3">
        <div className="h-5 w-40 rounded-md bg-sunk" />
        <div className="h-4 w-full rounded-md bg-sunk" />
        <div className="h-24 w-full rounded-xl bg-sunk" />
      </Card>
    </div>
  );
}

export function ClaudeContextPage() {
  const { data, isError, refetch, isFetching } = useQuery({
    queryKey: ["claude-context"],
    queryFn: () => apiFetch<ClaudeContext>("/claude/context"),
    refetchInterval: 60_000,
  });

  if (isError && !data) {
    return (
      <Shell>
        <Card as="div">
          <p className="text-sm">Could not load what Claude knows. Check that the web API is running, then try again.</p>
          <div className="mt-3">
            <Button variant="secondary" onClick={() => void refetch()} disabled={isFetching}>
              Try again
            </Button>
          </div>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      {data ? (
        <>
          <RegimeCard ctx={data} />
          <PictureCard ctx={data} />
          <CallsCard ctx={data} />
          <DroppedCard ctx={data} />
          <NamesCard ctx={data} />
        </>
      ) : (
        <Loading />
      )}
    </Shell>
  );
}
