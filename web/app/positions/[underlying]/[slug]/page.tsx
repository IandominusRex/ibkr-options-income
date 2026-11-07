"use client";

import { use } from "react";
import { PositionPage } from "@/features/position/PositionPage";
import { decodeSegment } from "@/lib/segment";

/** A held position's own page (web Home follow-ups): the underlying's chart, the trade that opened
 *  it, how it stands now, and the headlines. Reached from a row of Home's Positions card. */
export default function PositionRoute({ params }: { params: Promise<{ underlying: string; slug: string }> }) {
  const { underlying, slug } = use(params);
  return <PositionPage underlying={decodeSegment(underlying).toUpperCase()} slug={decodeSegment(slug)} />;
}
