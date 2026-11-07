import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/features/position/PositionPage", () => ({
  PositionPage: ({ underlying, slug }: { underlying: string; slug: string }) => (
    <p data-testid="position">{`${underlying}|${slug}`}</p>
  ),
}));

import PositionRoute from "./page";

describe("PositionRoute", () => {
  it("keeps a malformed escape in the URL as it came, not an error page", async () => {
    const params = Promise.resolve({ underlying: "aapl%", slug: "short-put-%zz" });
    await act(async () => {
      render(
        <Suspense fallback={null}>
          <PositionRoute params={params} />
        </Suspense>,
      );
    });
    expect(await screen.findByTestId("position")).toHaveTextContent("AAPL%|short-put-%zz");
  });

  it("still decodes a well-formed segment", async () => {
    const params = Promise.resolve({ underlying: "brk%2Eb", slug: "a%20b" });
    await act(async () => {
      render(
        <Suspense fallback={null}>
          <PositionRoute params={params} />
        </Suspense>,
      );
    });
    expect(await screen.findByTestId("position")).toHaveTextContent("BRK.B|a b");
  });
});
