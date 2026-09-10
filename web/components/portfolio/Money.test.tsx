import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Money } from "./Money";

describe("Money", () => {
  it("renders null as unknown, never as a zero", () => {
    render(<Money value={null} kind="realized" />);
    expect(screen.queryByText("$0.00")).toBeNull();
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.getByText(/n\/a/i)).toBeInTheDocument();
  });

  it("renders undefined as unknown too", () => {
    render(<Money value={undefined} kind="value" />);
    expect(screen.getByText(/n\/a/i)).toBeInTheDocument();
  });

  it("renders the unknown figure with the hatch texture, not colour alone", () => {
    render(<Money value={null} kind="realized" />);
    const el = screen.getByText(/n\/a/i);
    expect(el.className).toContain("hatch");
    expect(el.className).toContain("text-unknown");
  });

  it("renders a real zero as a zero", () => {
    render(<Money value={0} kind="realized" />);
    expect(screen.getByText("$0")).toBeInTheDocument();
  });

  it("carries the sign in the text, not only in the colour", () => {
    render(<Money value={-125.5} kind="unrealized" signed />);
    expect(screen.getByText(/-\$125\.50/)).toBeInTheDocument();
  });

  it("renders a leading plus on a signed positive figure", () => {
    render(<Money value={125.5} kind="unrealized" signed />);
    expect(screen.getByText(/\+\$125\.50/)).toBeInTheDocument();
  });

  it("does not add a plus sign when signed is off", () => {
    render(<Money value={125.5} kind="value" />);
    expect(screen.queryByText(/\+\$125\.50/)).toBeNull();
    expect(screen.getByText(/\$125\.50/)).toBeInTheDocument();
  });

  it("distinguishes a realized figure from an unrealized one", () => {
    const { container: a } = render(<Money value={100} kind="realized" />);
    const { container: b } = render(<Money value={100} kind="unrealized" />);
    expect(a.textContent).not.toEqual(b.textContent);
  });

  it("says so when a figure excludes commissions", () => {
    render(<Money value={100} kind="realized" complete={false} />);
    expect(screen.getByText(/gross/i)).toBeInTheDocument();
  });

  it("does not say gross when complete is true (the default)", () => {
    render(<Money value={100} kind="realized" />);
    expect(screen.queryByText(/gross/i)).toBeNull();
  });

  it("applies tabular figures", () => {
    const { container } = render(<Money value={1234.5} kind="value" />);
    expect(container.querySelector(".tabular")).not.toBeNull();
  });

  it("applies tabular figures to an unknown value too, so columns still align", () => {
    const { container } = render(<Money value={null} kind="value" />);
    expect(container.querySelector(".tabular")).not.toBeNull();
  });
});
