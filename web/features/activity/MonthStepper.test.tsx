import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MonthStepper } from "./MonthStepper";

const stepper = (over: Partial<Parameters<typeof MonthStepper>[0]> = {}) => {
  const onChange = vi.fn();
  render(<MonthStepper month="2026-09" current="2026-10" floor={null} onChange={onChange} {...over} />);
  return onChange;
};

describe("MonthStepper", () => {
  it("names the month and steps back and forward", () => {
    const onChange = stepper();
    expect(screen.getByText("September 2026")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-08");
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-10");
  });
  it("offers This month only away from this month, and goes there", () => {
    const onChange = stepper();
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(onChange).toHaveBeenCalledWith("2026-10");
  });
  it("has no This month on this month, and no way forward", () => {
    stepper({ month: "2026-10" });
    expect(screen.queryByRole("button", { name: "This month" })).toBeNull();
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  });
  it("stops going back at the month the system began", () => {
    stepper({ month: "2026-06", floor: "2026-06" });
    expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled();
  });
  it("lets you go back when the floor is not known", () => {
    stepper({ month: "2020-01", floor: null });
    expect(screen.getByRole("button", { name: "Previous month" })).toBeEnabled();
  });
});
