import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChecksSection, type ChecksPayloadData } from "./ChecksSection";

function payload(overrides: Partial<ChecksPayloadData> = {}): ChecksPayloadData {
  return {
    categories: [
      {
        category: "value",
        passed: 4,
        failed: 1,
        unknown: 1,
        evaluable: 5,
        total: 6,
        not_applicable: false,
        note: null,
        checks: [
          {
            id: "value.pe_reasonable",
            category: "value",
            statement: "Is the P/E ratio below 22?",
            state: "PASS",
            actual: 18,
            threshold: 22,
            note: null,
          },
        ],
      },
      {
        category: "past",
        passed: 0,
        failed: 0,
        unknown: 0,
        evaluable: 0,
        total: 6,
        not_applicable: true,
        note: "Funds file no XBRL financial statements",
        checks: [],
      },
    ],
    warnings: [],
    ...overrides,
  };
}

describe("ChecksSection", () => {
  it("renders one ribbon per category", () => {
    render(<ChecksSection data={payload()} />);
    expect(screen.getByText("Value")).toBeDefined();
    expect(screen.getByText("Past performance")).toBeDefined();
  });

  it("expands a category's checks on click, and collapses on a second click", () => {
    render(<ChecksSection data={payload()} />);
    const button = screen.getByRole("button", { name: /value/i });
    expect(screen.queryByText("Is the P/E ratio below 22?")).toBeNull();

    fireEvent.click(button);
    expect(screen.getByText("Is the P/E ratio below 22?")).toBeDefined();

    fireEvent.click(button);
    expect(screen.queryByText("Is the P/E ratio below 22?")).toBeNull();
  });

  it("marks the expandable ribbon as a button with aria-expanded", () => {
    render(<ChecksSection data={payload()} />);
    const button = screen.getByRole("button", { name: /value/i });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
  });

  it("renders a not-applicable category's explanation and cannot be expanded", () => {
    render(<ChecksSection data={payload()} />);
    expect(screen.getByText("Funds file no XBRL financial statements")).toBeDefined();
    const button = screen.getByRole("button", { name: /past performance/i });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.click(button);
    expect(screen.queryByText(/is the/i)).toBeNull();
  });

  it("renders warnings when present", () => {
    render(
      <ChecksSection
        data={payload({
          warnings: [
            {
              level: "caution",
              title: "Daily-reset decay risk",
              detail: "Leveraged ETFs compound daily.",
            },
          ],
        })}
      />,
    );
    expect(screen.getByTestId("warning")).toBeDefined();
    expect(screen.getByText("Daily-reset decay risk")).toBeDefined();
  });

  it("renders no warnings block when there are none", () => {
    render(<ChecksSection data={payload()} />);
    expect(screen.queryByTestId("warning")).toBeNull();
  });
});
