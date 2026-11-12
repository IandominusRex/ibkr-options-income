import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { Card } from "./Card";
import { Meter } from "./Meter";
import { SegmentedControl } from "./SegmentedControl";
import { StatusWord } from "./StatusWord";

describe("Button", () => {
  it("dims a disabled quiet button without filling it, while a disabled primary or secondary drops to sunk", () => {
    render(
      <>
        <Button variant="quiet" disabled>Quiet</Button>
        <Button variant="primary" disabled>Primary</Button>
        <Button variant="secondary" disabled>Secondary</Button>
      </>,
    );
    const quiet = screen.getByRole("button", { name: "Quiet" });
    expect(quiet).toHaveClass("bg-transparent", "disabled:text-muted");
    expect(quiet.className).not.toContain("disabled:bg-sunk");
    for (const name of ["Primary", "Secondary"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("disabled:bg-sunk", "disabled:text-muted");
    }
  });

  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>Review</Button>);
    expect(screen.getByRole("button", { name: "Review" })).toHaveAttribute("type", "button");
  });
  it("marks its variant and fires onClick", () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" onClick={onClick}>
        Review
      </Button>,
    );
    const b = screen.getByRole("button", { name: "Review" });
    expect(b).toHaveAttribute("data-variant", "primary");
    fireEvent.click(b);
    expect(onClick).toHaveBeenCalledOnce();
  });
  it("does not fire when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" disabled onClick={onClick}>
        Review
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Card", () => {
  it("renders as a section by default and as the requested element otherwise", () => {
    const { container, rerender } = render(<Card>pay</Card>);
    expect(container.firstElementChild?.tagName).toBe("SECTION");
    rerender(<Card as="aside">pay</Card>);
    expect(container.firstElementChild?.tagName).toBe("ASIDE");
  });
});

describe("SegmentedControl", () => {
  const options = [
    { value: "all", label: "All" },
    { value: "csp", label: "CSPs", count: 3 },
    { value: "cc", label: "CCs", count: 0 },
    { value: "spread", label: "Credit spreads", count: null },
  ] as const;

  it("is a labelled group whose selected button is aria-pressed", () => {
    render(
      <SegmentedControl label="Strategy" options={[...options]} value="csp" onChange={() => {}} />,
    );
    expect(screen.getByRole("group", { name: "Strategy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /CSPs/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  });
  it("shows a real zero count but no count at all when it is unknown", () => {
    render(
      <SegmentedControl label="Strategy" options={[...options]} value="all" onChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "CCs 0" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Credit spreads" })).toBeInTheDocument();
  });
  it("calls onChange with the option value", () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="Strategy" options={[...options]} value="all" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /CSPs/ }));
    expect(onChange).toHaveBeenCalledWith("csp");
  });
});

describe("StatusWord", () => {
  it("carries its tone as data so the word, not the colour, is the signal", () => {
    render(<StatusWord tone="flag">Assignment likely</StatusWord>);
    expect(screen.getByText("Assignment likely")).toHaveAttribute("data-tone", "flag");
  });
});

describe("Meter", () => {
  it("reports progress as a percentage", () => {
    render(<Meter value={1413.6} max={2000} label="October target" />);
    const m = screen.getByRole("progressbar", { name: "October target" });
    expect(m).toHaveAttribute("aria-valuenow", "71");
    expect(m).toHaveAttribute("aria-valuetext", "71%");
  });
  it("caps at 100 and floors at 0", () => {
    const { rerender } = render(<Meter value={5000} max={2000} label="t" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    rerender(<Meter value={-50} max={2000} label="t" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
  it("is hatched and says n/a when there is no target", () => {
    render(<Meter value={300} max={null} label="t" />);
    const m = screen.getByRole("progressbar");
    expect(m).not.toHaveAttribute("aria-valuenow");
    expect(m).toHaveAttribute("aria-valuetext", "n/a");
    expect(m.className).toContain("hatch");
  });
});
