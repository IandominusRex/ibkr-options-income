import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";

// DecideControls (lib/commands.ts) persists in-flight commands to localStorage
// keyed by approval id. Test files reuse the same small set of approval ids
// (1, 41, 42, ...) across cases, and jsdom's localStorage is NOT reset between
// tests on its own — without this, a command persisted by one test would leak
// into the next test's fresh mount of the same approval id and corrupt its
// initial state.
afterEach(() => {
  localStorage.clear();
});

// jsdom has no matchMedia. Components query it for prefers-reduced-motion;
// a permissive stub lets tests override via vi.stubGlobal or run with the
// default (no preference).
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: (_: string, __: unknown) => {},
      removeEventListener: (_: string, __: unknown) => {},
      addListener: (_: unknown) => {},
      removeListener: (_: unknown) => {},
      dispatchEvent: (_: unknown) => false,
    }),
  });
}

// jsdom has no ResizeObserver either. Recharts' ResponsiveContainer (the
// equity chart, M5 Task 5.5) subscribes to one on mount; without a stub every
// chart render throws before a single assertion runs.
if (typeof window !== "undefined" && typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}