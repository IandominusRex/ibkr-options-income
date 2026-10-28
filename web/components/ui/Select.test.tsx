import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Select } from "./Select";

const OPTIONS = [
  { value: "all", label: "All" },
  { value: "paper", label: "Paper" },
  { value: "live", label: "Live" },
];

function Harness({ onChange = () => {} }: { onChange?: (v: string) => void }) {
  const [v, setV] = useState("all");
  return (
    <>
      <label htmlFor="book">Book</label>
      <Select
        id="book"
        value={v}
        options={OPTIONS}
        onChange={(next) => {
          setV(next);
          onChange(next);
        }}
      />
    </>
  );
}

describe("Select", () => {
  it("shows the chosen option's label on a trigger its label points at", () => {
    render(<Harness />);
    const trigger = screen.getByLabelText("Book");
    expect(trigger).toHaveTextContent("All");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("opens a listbox with every option and marks the chosen one", () => {
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("Book"));
    expect(screen.getByLabelText("Book")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["All", "Paper", "Live"]);
    expect(screen.getByRole("option", { name: "All" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("option", { name: "Paper" })).toHaveAttribute("aria-selected", "false");
  });

  it("chooses with a click, reports the value and closes", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Book"));
    fireEvent.click(screen.getByRole("option", { name: "Paper" }));
    expect(onChange).toHaveBeenCalledWith("paper");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByLabelText("Book")).toHaveTextContent("Paper");
  });

  it("is driven from the keyboard: arrows open and move, Enter chooses, Escape closes and keeps focus", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const trigger = screen.getByLabelText("Book");
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" }); // stops at the last option
    expect(trigger).toHaveAttribute("aria-activedescendant", expect.stringMatching(/-2$/));
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("live");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger).toHaveFocus();

    fireEvent.keyDown(trigger, { key: " " });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("jumps to an option by the letters typed", () => {
    render(<Harness />);
    const trigger = screen.getByLabelText("Book");
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.keyDown(trigger, { key: "l" });
    expect(trigger).toHaveAttribute("aria-activedescendant", expect.stringMatching(/-2$/));
  });

  it("closes on a press outside it, without choosing", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Book"));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not open when disabled", () => {
    render(<Select value="all" options={OPTIONS} onChange={() => {}} disabled aria-label="Book" />);
    fireEvent.click(screen.getByRole("combobox", { name: "Book" }));
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
