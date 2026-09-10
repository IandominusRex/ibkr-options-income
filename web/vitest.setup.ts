import "@testing-library/jest-dom/vitest";

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