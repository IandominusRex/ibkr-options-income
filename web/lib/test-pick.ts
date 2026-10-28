import { fireEvent, screen, within } from "@testing-library/react";
import { longDay, parseIso } from "@/components/ui/dates";

/** Open a `Select` and choose the option with this label. */
export function chooseOption(trigger: HTMLElement, label: string) {
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("option", { name: label }));
}

/** Open a `DatePicker`, page to the month holding `iso` and choose that day. */
export function chooseDay(trigger: HTMLElement, iso: string) {
  fireEvent.click(trigger);
  const panel = within(screen.getByRole("dialog", { name: "Choose a day" }));
  const want = parseIso(iso)!;
  for (let i = 0; i < 120; i++) {
    const shown = new Date(`1 ${panel.getByRole("grid").getAttribute("aria-label")} UTC`);
    const gap = (want.y - shown.getUTCFullYear()) * 12 + (want.m - 1 - shown.getUTCMonth());
    if (gap === 0) break;
    fireEvent.click(panel.getByRole("button", { name: gap > 0 ? "Next month" : "Previous month" }));
  }
  fireEvent.click(panel.getByRole("button", { name: longDay(iso) }));
}
