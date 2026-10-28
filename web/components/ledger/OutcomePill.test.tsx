import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OutcomePill } from "./OutcomePill";

describe("OutcomePill", () => {
  it("prints the outcome in words", () => {
    render(<OutcomePill outcome="Called away" />);
    expect(screen.getByText("Called away")).toBeInTheDocument();
  });
  it("marks an outcome the operator set, in words for a screen reader", () => {
    render(<OutcomePill outcome="Expired" overridden />);
    expect(screen.getByLabelText("overridden")).toHaveTextContent("*");
  });
  it("marks nothing for a computed outcome", () => {
    render(<OutcomePill outcome="Expired" />);
    expect(screen.queryByLabelText("overridden")).toBeNull();
  });
});
