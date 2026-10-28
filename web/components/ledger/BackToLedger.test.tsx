import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BackToLedger } from "./BackToLedger";

describe("BackToLedger", () => {
  it("leads back to the Ledger view on Activity", () => {
    render(<BackToLedger />);
    expect(screen.getByRole("link", { name: "Back to Activity, Ledger" })).toHaveAttribute(
      "href",
      "/activity?view=ledger",
    );
  });
});
