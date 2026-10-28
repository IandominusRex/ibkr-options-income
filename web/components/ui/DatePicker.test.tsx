import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DatePicker } from "./DatePicker";

function Harness({ initial = "", min, max, onChange = () => {} }: { initial?: string; min?: string; max?: string; onChange?: (v: string) => void }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <label htmlFor="since">Since</label>
      <DatePicker
        id="since"
        value={v}
        min={min}
        max={max}
        onChange={(next) => {
          setV(next);
          onChange(next);
        }}
      />
    </>
  );
}

const open = () => fireEvent.click(screen.getByLabelText("Since"));
const panel = () => within(screen.getByRole("dialog", { name: "Choose a day" }));

describe("DatePicker", () => {
  it("says Any day for no day, and writes a chosen day short", () => {
    const { unmount } = render(<Harness />);
    expect(screen.getByLabelText("Since")).toHaveTextContent("Any day");
    unmount();
    render(<Harness initial="2026-10-15" />);
    expect(screen.getByLabelText("Since")).toHaveTextContent("Oct 15, 2026");
  });

  it("opens on the month of the chosen day, Monday-first, with the chosen day pressed", () => {
    render(<Harness initial="2026-10-15" />);
    open();
    expect(panel().getByRole("grid")).toHaveAccessibleName("October 2026");
    expect(panel().getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]);
    expect(panel().getByRole("button", { name: "Thursday, October 15, 2026" })).toHaveAttribute("aria-pressed", "true");
    expect(panel().getByRole("button", { name: "Friday, October 16, 2026" })).toHaveAttribute("aria-pressed", "false");
    expect(panel().getAllByRole("button", { name: /, 2026$/ })).toHaveLength(31);
  });

  it("chooses a day with a click, reports it and closes", () => {
    const onChange = vi.fn();
    render(<Harness initial="2026-10-15" onChange={onChange} />);
    open();
    fireEvent.click(panel().getByRole("button", { name: "Tuesday, October 20, 2026" }));
    expect(onChange).toHaveBeenCalledWith("2026-10-20");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Since")).toHaveTextContent("Oct 20, 2026");
  });

  it("pages by month with the arrows", () => {
    render(<Harness initial="2026-10-15" />);
    open();
    fireEvent.click(panel().getByRole("button", { name: "Previous month" }));
    expect(panel().getByRole("grid")).toHaveAccessibleName("September 2026");
    fireEvent.click(panel().getByRole("button", { name: "Next month" }));
    fireEvent.click(panel().getByRole("button", { name: "Next month" }));
    expect(panel().getByRole("grid")).toHaveAccessibleName("November 2026");
  });

  it("moves by day and week with the arrow keys and chooses with Enter", () => {
    const onChange = vi.fn();
    render(<Harness initial="2026-10-15" onChange={onChange} />);
    open();
    const day = () => panel().getByRole("button", { name: "Thursday, October 15, 2026" });
    expect(day()).toHaveFocus();
    fireEvent.keyDown(day(), { key: "ArrowRight" });
    fireEvent.keyDown(panel().getByRole("button", { name: "Friday, October 16, 2026" }), { key: "ArrowDown" });
    const landed = panel().getByRole("button", { name: "Friday, October 23, 2026" });
    expect(landed).toHaveFocus();
    fireEvent.click(landed);
    expect(onChange).toHaveBeenCalledWith("2026-10-23");
  });

  it("crosses into the next month by keyboard", () => {
    render(<Harness initial="2026-10-31" />);
    open();
    fireEvent.keyDown(panel().getByRole("button", { name: "Saturday, October 31, 2026" }), { key: "ArrowRight" });
    expect(panel().getByRole("grid")).toHaveAccessibleName("November 2026");
    expect(panel().getByRole("button", { name: "Sunday, November 1, 2026" })).toHaveFocus();
  });

  it("greys out days outside min and max and refuses them", () => {
    const onChange = vi.fn();
    render(<Harness initial="2026-10-15" min="2026-10-10" max="2026-10-20" onChange={onChange} />);
    open();
    expect(panel().getByRole("button", { name: "Friday, October 9, 2026" })).toBeDisabled();
    expect(panel().getByRole("button", { name: "Wednesday, October 21, 2026" })).toBeDisabled();
    expect(panel().getByRole("button", { name: "Saturday, October 10, 2026" })).toBeEnabled();
    fireEvent.click(panel().getByRole("button", { name: "Wednesday, October 21, 2026" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("stops the arrows where the month holds no allowed day", () => {
    render(<Harness initial="2026-10-15" min="2026-10-10" max="2026-10-20" />);
    open();
    expect(panel().getByRole("button", { name: "Previous month" })).toBeDisabled();
    expect(panel().getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  it("clears to no day, and offers Clear only when there is one", () => {
    const onChange = vi.fn();
    const { unmount } = render(<Harness onChange={onChange} />);
    open();
    expect(panel().getByRole("button", { name: "Clear" })).toBeDisabled();
    unmount();
    render(<Harness initial="2026-10-15" onChange={onChange} />);
    open();
    fireEvent.click(panel().getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenCalledWith("");
    expect(screen.getByLabelText("Since")).toHaveTextContent("Any day");
  });

  it("closes on Escape and hands focus back to the trigger", () => {
    render(<Harness initial="2026-10-15" />);
    open();
    fireEvent.keyDown(panel().getByRole("button", { name: "Thursday, October 15, 2026" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Since")).toHaveFocus();
  });
});
