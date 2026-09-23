"use client";

import clsx from "clsx";
import type { TabKey } from "./types";
import { TAB_META } from "./types";

const MAIN_STAGES: TabKey[] = ["data", "ideas", "gate", "claude", "execution"];

function StageBox({
  tab,
  active,
  onNavigate,
  variant = "main",
}: {
  tab: TabKey;
  active: boolean;
  onNavigate: (tab: TabKey) => void;
  variant?: "main" | "side";
}) {
  return (
    <button
      type="button"
      onClick={() => onNavigate(tab)}
      aria-current={active ? "step" : undefined}
      className={clsx(
        "rounded-md border px-3 py-2 text-left text-sm transition-colors",
        variant === "main" ? "min-w-[108px]" : "min-w-[140px]",
        active
          ? "border-focus bg-elevated text-content"
          : "border-border bg-surface text-muted hover:border-focus/60 hover:text-content",
      )}
    >
      {TAB_META[tab].label}
    </button>
  );
}

function Arrow() {
  return (
    <span aria-hidden="true" className="px-1 text-muted">
      &rarr;
    </span>
  );
}

/**
 * The "you are here" map every System Explanation subtab mounts at the top of its panel.
 * It is the one piece of UI that makes the tie-between-tabs concrete: the same five-box
 * chain renders on every subtab with that subtab's own box highlighted, plus the two
 * pieces that sit outside the straight-line pipeline - the monitor loop that feeds rolls
 * back into the gate, and this dashboard, which only ever reads the trail the pipeline
 * leaves behind and queues commands into the same approval flow Telegram uses.
 *
 * Every box is a real nav control (onNavigate), not decoration - clicking anywhere on the
 * map jumps the shell to that subtab, so the map doubles as navigation.
 */
export function PipelineMap({
  active,
  onNavigate,
}: {
  active: TabKey | null;
  onNavigate: (tab: TabKey) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-1">
        {MAIN_STAGES.map((tab, i) => (
          <span key={tab} className="flex items-center">
            <StageBox tab={tab} active={active === tab} onNavigate={onNavigate} />
            {i < MAIN_STAGES.length - 1 && <Arrow />}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted">
        <span>once filled &darr;</span>
        <StageBox tab="watching" active={active === "watching"} onNavigate={onNavigate} variant="side" />
        <span>rolls &amp; closes re-enter the gate &#8635;</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
        <StageBox tab="web" active={active === "web"} onNavigate={onNavigate} variant="side" />
        <span>reads the gate &amp; approval trail, writes commands into the same approval flow</span>
      </div>
    </div>
  );
}
