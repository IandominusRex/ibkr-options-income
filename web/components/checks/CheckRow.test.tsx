import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckRow } from "./CheckRow";

describe("CheckRow", () => {
  it("shows the statement, actual value, threshold, and state for a pass", () => {
    render(
      <CheckRow statement="Is the P/E ratio below 22?" state="PASS" actual={18} threshold={22} />,
    );
    expect(screen.getByText("Is the P/E ratio below 22?")).toBeDefined();
    expect(screen.getByText("18")).toBeDefined();
    expect(screen.getByText("22")).toBeDefined();
    expect(screen.getByText("Pass")).toBeDefined();
  });

  it("renders an unknown row's actual as n/a in text-unknown, never 0", () => {
    render(
      <CheckRow
        statement="Is the dividend yield above 1%?"
        state="UNKNOWN"
        actual={null}
        threshold={1}
        note="Input data unavailable"
      />,
    );
    const actual = screen.getByText("n/a");
    expect(actual.className).toContain("text-unknown");
    expect(screen.queryByText("0")).toBeNull();
  });

  it("shows the note for an unknown row", () => {
    render(
      <CheckRow
        statement="Is the dividend yield above 1%?"
        state="UNKNOWN"
        actual={null}
        threshold={1}
        note="Input data unavailable"
      />,
    );
    expect(screen.getByText("Input data unavailable")).toBeDefined();
  });

  it("formats a between threshold as a range", () => {
    render(
      <CheckRow
        statement="Is the payout ratio between 0 and 90%?"
        state="PASS"
        actual={25}
        threshold={[0, 90]}
      />,
    );
    expect(screen.getByText("0 – 90")).toBeDefined();
  });

  it("carries state as a data attribute, not colour-only", () => {
    render(
      <CheckRow statement="Is the P/E ratio below 22?" state="FAIL" actual={30} threshold={22} />,
    );
    expect(screen.getByTestId("check-row").dataset.state).toBe("fail");
  });
});
