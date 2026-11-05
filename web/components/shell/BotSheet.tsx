"use client";

import { AutonomyControl } from "@/components/options/AutonomyControl";
import { DrainWarning } from "@/components/shell/DrainWarning";
import { HaltControl } from "@/components/options/HaltControl";
import { RollModeControl } from "@/components/options/RollModeControl";
import type { ControlsResponse } from "@/components/options/types";
import { Sheet } from "@/components/ui/Sheet";

/**
 * Halt is one tap, resume needs RESUME, rung changes confirm: all unchanged, only relocated.
 * The "not draining" warning sits right above the controls, as it does beside the strip on
 * /trades: a halt queued while no drain picks it up is the worst case, and the sheet re-renders
 * with each controls refetch, so it appears even if the drain dies while the sheet is open.
 */
export function BotSheet({
  open,
  onClose,
  controls,
}: {
  open: boolean;
  onClose: () => void;
  controls: ControlsResponse;
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Bot controls">
      <p className="text-sm text-muted">
        Mode: <span className="font-semibold text-content">{controls.mode}</span>
      </p>
      <div className="mt-4 grid gap-5">
        {!controls.drain_healthy && <DrainWarning lastSeen={controls.drain_last_seen} />}
        <HaltControl
          halted={controls.halted}
          haltReason={controls.halt_reason}
          haltedAt={controls.halted_at}
          drainHealthy={controls.drain_healthy}
        />
        <AutonomyControl autonomy={controls.autonomy} rungs={controls.rungs} drainHealthy={controls.drain_healthy} />
        <RollModeControl mode={controls.roll_mode ?? "auto"} drainHealthy={controls.drain_healthy} />
      </div>
    </Sheet>
  );
}
