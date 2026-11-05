"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

/** The one error page (web overhaul Part 4, ruling 24). It says what happened, that nothing changed and offers
 *  one act. The error's message stays in the console: it can name a URL or a table, and it is not for this screen.
 *  Secondary, never lime: Try again repeats a read, it does not act on the account. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="mx-auto max-w-[720px] px-4 py-5 md:px-7 md:py-6">
      <Card>
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">This page could not be shown</h1>
        <p className="mt-2 text-sm text-muted">Nothing was changed. The rest of the console still works.</p>
        {error.digest ? <p className="tabular mt-2 font-mono text-[0.8125rem] text-muted">Reference {error.digest}</p> : null}
        <Button variant="secondary" className="mt-4" onClick={reset}>
          Try again
        </Button>
      </Card>
    </div>
  );
}
