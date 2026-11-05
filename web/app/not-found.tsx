import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui/Card";

export const metadata: Metadata = { title: "Not found" };

/** The one not-found page (web overhaul Part 4, ruling 24): what happened, that nothing changed, one way out.
 *  The link wears the secondary Button's face; it is a link because it goes somewhere. No lime: nothing here is an act. */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-[720px] px-4 py-5 md:px-7 md:py-6">
      <Card>
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">This page does not exist</h1>
        <p className="mt-2 text-sm text-muted">The address may be old or mistyped. Nothing was changed.</p>
        <Link
          href="/"
          className="mt-4 inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content hover:bg-sunk-deep"
        >
          Go to Home
        </Link>
      </Card>
    </div>
  );
}
