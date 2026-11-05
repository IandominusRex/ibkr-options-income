import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ErrorPage from "./error";
import NotFound, { metadata } from "./not-found";

describe("the not-found page (web overhaul Part 4, ruling 24)", () => {
  it("says what happened in one heading and one sentence", () => {
    render(<NotFound />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("This page does not exist");
    expect(screen.getByText("The address may be old or mistyped. Nothing was changed.")).toBeTruthy();
  });

  it("offers one way out: a link to Home", () => {
    render(<NotFound />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("is titled Not found", () => {
    expect(metadata.title).toBe("Not found");
  });

  it("never uses lime, which means act", () => {
    const { container } = render(<NotFound />);
    expect(container.querySelector(".bg-primary")).toBeNull();
    expect(container.innerHTML).not.toContain("bg-primary");
  });
});

describe("the error page (web overhaul Part 4, ruling 24)", () => {
  const boom = Object.assign(new Error("boom"), { digest: "abc123" });

  it("says what happened and that nothing changed", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorPage error={boom} reset={() => {}} />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("This page could not be shown");
    expect(screen.getByText("Nothing was changed. The rest of the console still works.")).toBeTruthy();
  });

  it("Try again calls reset exactly once", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reset = vi.fn();
    render(<ErrorPage error={boom} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("shows the reference only when the error has a digest", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<ErrorPage error={boom} reset={() => {}} />);
    expect(screen.getByText("Reference abc123")).toBeTruthy();
    unmount();
    render(<ErrorPage error={new Error("plain")} reset={() => {}} />);
    expect(screen.queryByText(/Reference/)).toBeNull();
  });

  it("logs the error once, for the operator's console", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    spy.mockClear();
    render(<ErrorPage error={boom} reset={() => {}} />);
    expect(spy).toHaveBeenCalledWith(boom);
  });

  it("never uses lime, which means act", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { container } = render(<ErrorPage error={boom} reset={() => {}} />);
    expect(container.innerHTML).not.toContain("bg-primary");
    expect(container.querySelector('[data-variant="primary"]')).toBeNull();
  });

  it("does not print the error's message to the screen", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorPage error={boom} reset={() => {}} />);
    expect(screen.queryByText(/boom/)).toBeNull();
  });
});
