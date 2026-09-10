import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { apiFetch } from "@/lib/api";

// Shared test helper (built for M3 Task 3.2, reused by Tasks 3.3-3.5): every
// components/options/*.test.tsx file before this one duplicated the same three
// lines inline — a `withClient()` QueryClientProvider wrapper, `vi.mock("@/lib/api")`,
// and a per-file `apiFetch.mockImplementation((path) => {...})` (see
// ApprovalDetail.test.tsx:7-15 and ShortsTable.test.tsx:7-19,61-83 for the shape this
// replaces). Centralising it here means later portfolio test files answer with a
// plain path-to-response map instead of reinventing the switch statement.
//
// vi.mock is called here, at this file's module scope, not inside renderWithQuery.
// Vitest hoists it to the top of THIS file's evaluation, and because this module is
// a static import of every test file that calls renderWithQuery, it is fully
// evaluated (mock registered) before the component-under-test's own `import {
// apiFetch } from "@/lib/api"` resolves — so the mock is in place without every
// test file needing its own vi.mock call.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return { ...(actual as object), apiFetch: vi.fn() };
});

type ApiFetchMock = {
  mockImplementation: (fn: (path: string) => Promise<unknown>) => void;
  mock: { calls: unknown[][] };
};

/**
 * The mocked `apiFetch` itself, for a test that needs to assert on calls
 * (count, arguments) rather than only on rendered output - e.g. "switching
 * tabs does not refetch". A test file must read this export rather than
 * writing its own `import { apiFetch } from "@/lib/api"`: importing the real
 * specifier directly races the mock registration above (whichever import of
 * "@/lib/api" resolves first in the module graph wins, and a sibling import
 * ahead of this file's in the same test file resolves before vi.mock
 * hoists), and the resulting `apiFetch` binding is not guaranteed to be the
 * mock. Going through this export instead - already resolved, by definition,
 * since this module is where the mock is declared - sidesteps that.
 */
export const apiFetchMock = apiFetch as unknown as ApiFetchMock;

/**
 * Renders `ui` inside a fresh QueryClientProvider (retries off, so a mocked
 * rejection surfaces on the first render rather than after retry backoff) with
 * `apiFetch` mocked to answer per path from `responses`.
 *
 * Matching: an exact key match wins; otherwise the first key `path` starts with
 * (so "/options/shorts?symbol=NVDA" still resolves against a "/options/shorts"
 * entry, matching the startsWith convention ShortsTable.test.tsx already uses).
 * A path with no matching key throws immediately instead of resolving `undefined`,
 * so a missing mock fails loudly at the fetch site, not several assertions later.
 */
export function renderWithQuery(ui: ReactElement, responses: Record<string, unknown>) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path in responses) return responses[path];
    const key = Object.keys(responses).find((k) => path.startsWith(k));
    if (key !== undefined) return responses[key];
    throw new Error(`renderWithQuery: no mocked response for path "${path}"`);
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}
