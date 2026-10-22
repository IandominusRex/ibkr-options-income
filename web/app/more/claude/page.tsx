"use client";

import { ClaudeContextPage } from "@/features/claude-context/ClaudeContextPage";

/** What Claude knows: the market picture, the limits it sets, and what each Claude call reads.
 *  Read-only; reached from a row on More. */
export default function ClaudeContextRoute() {
  return <ClaudeContextPage />;
}
