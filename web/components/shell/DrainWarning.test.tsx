import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DrainWarning } from "./DrainWarning";

describe("DrainWarning", () => {
  it("says the trading service is not draining, and that it has never run", () => {
    render(<DrainWarning lastSeen={null} />);
    const warn = screen.getByTestId("drain-dead-warning");
    expect(warn.textContent).toContain("the trading service is not draining commands");
    expect(warn.textContent).toContain("(it has never run)");
  });

  it("names when the drain was last seen, and does not say it never ran", () => {
    render(<DrainWarning lastSeen={new Date(Date.now() - 3 * 3_600_000).toISOString()} />);
    const warn = screen.getByTestId("drain-dead-warning");
    expect(warn.textContent).toContain("the trading service is not draining commands");
    expect(warn.textContent).toContain("(last seen ");
    expect(warn.textContent).not.toContain("never");
  });
});
