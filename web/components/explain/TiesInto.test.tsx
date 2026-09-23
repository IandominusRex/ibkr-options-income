import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TiesInto } from "./TiesInto";

describe("TiesInto", () => {
  it("renders nothing when there are no ties", () => {
    const { container } = render(<TiesInto items={[]} onNavigate={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a chip per tie with its label and reason", () => {
    render(
      <TiesInto
        items={[{ tab: "gate", reason: "every candidate has to clear this next." }]}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByText("The Risk Gate")).toBeDefined();
    expect(screen.getByText("every candidate has to clear this next.")).toBeDefined();
  });

  it("navigates to the tied tab on click", () => {
    const onNavigate = vi.fn();
    render(
      <TiesInto
        items={[{ tab: "claude", reason: "gets the read-only research too." }]}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onNavigate).toHaveBeenCalledWith("claude");
  });
});
