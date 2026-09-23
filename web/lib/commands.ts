import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiFetch } from "./api";

/**
 * A command's status, matching `CommandStatus` in src/api/models/commands.py.
 * `confirm_token` is present only while a live-mode order-reaching intent is
 * awaiting its second confirmation.
 */
export type CommandStatus = {
  id: number;
  kind: string;
  status: "pending" | "applied" | "failed" | "expired";
  result: Record<string, unknown> | null;
  needs_confirmation: boolean;
  confirm_token: string | null;
  created_at: string;
  applied_at: string | null;
  as_of: string;
};

export type SubmitResult = CommandStatus & { created: boolean };

export async function submitCommand(
  kind: string,
  payload: unknown,
): Promise<SubmitResult> {
  return apiFetch<SubmitResult>("/commands", {
    method: "POST",
    body: JSON.stringify({ kind, payload }),
  });
}

export async function confirmCommand(id: number, confirmToken: string): Promise<void> {
  await apiFetch<unknown>(`/commands/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirm_token: confirmToken }),
  });
}

/**
 * The write path for the two path-param universe routes (M7 Task 7.4):
 * `POST /universe/{list_name}/{symbol}` and `DELETE /universe/{list_name}/{symbol}`.
 * Unlike `submitCommand`, these take no body — the intent lives entirely in the
 * URL. Both return the same `CommandStatus & { created: boolean }` shape.
 * Neither route ever returns `needs_confirmation: true` (universe kinds never
 * need the live second-confirmation step `HaltControl` and friends handle for
 * halt/resume), so callers do not need to build that flow for this helper.
 */
export async function submitUniverseCommand(
  action: "add" | "remove",
  listName: string,
  symbol: string,
): Promise<SubmitResult> {
  return apiFetch<SubmitResult>(
    `/universe/${listName}/${encodeURIComponent(symbol)}`,
    { method: action === "add" ? "POST" : "DELETE" },
  );
}

const TERMINAL: CommandStatus["status"][] = ["applied", "failed", "expired"];

// Per-subject in-flight command, persisted to localStorage so it survives a full
// page reload and is visible from any surface that mounts the same decide-flow
// control for that subject — not just a tab-switch remount. Only ever holds a
// command whose `status` is still "pending" (including one awaiting the live
// second confirmation); a terminal command is removed, not stored.
//
// The "subject" key is a plain approval id (number) for <DecideControls/> (the
// approval card and the detail page share one key per approval, unchanged
// format for backward compatibility with what's already on disk) or a
// namespaced string for the other two decide-flow controls, which aren't keyed
// by approval id at all: <ShortsRow/> proposes a roll keyed by
// `short:{position_symbol}`, <AssessedRow/> promotes keyed by
// `promote:{candidate_id}`. The namespace prefix keeps these from ever
// colliding with an approval id or each other; `loadAllPersistedCommands`
// (approval ids only, for the options page's `submitted` map) already skips
// them for free since a namespaced key doesn't parse as a number.
const COMMAND_STORAGE_PREFIX = "ibkr-options:command:";

function commandStorageKey(subject: string | number): string {
  return `${COMMAND_STORAGE_PREFIX}${subject}`;
}

export function loadPersistedCommand(subject: string | number): CommandStatus | null {
  try {
    const raw = localStorage.getItem(commandStorageKey(subject));
    if (!raw) return null;
    return JSON.parse(raw) as CommandStatus;
  } catch {
    // Convenience persistence only — a private window, cleared site data, or a
    // browser that blocks storage access must not break the decide flow.
    return null;
  }
}

export function savePersistedCommand(
  subject: string | number,
  command: CommandStatus | null,
): void {
  try {
    if (command === null) {
      localStorage.removeItem(commandStorageKey(subject));
    } else {
      localStorage.setItem(commandStorageKey(subject), JSON.stringify(command));
    }
  } catch {
    // Best-effort only, see loadPersistedCommand.
  }
}

/** Every approval id with a still-in-flight persisted command, keyed by id. Used
 * to seed the options page's `submitted` map on mount so a card's tab placement
 * (Approvals vs Submitted) survives a reload, not just its receipt. */
export function loadAllPersistedCommands(): Map<number, CommandStatus> {
  const out = new Map<number, CommandStatus>();
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(COMMAND_STORAGE_PREFIX)) continue;
      const id = Number(key.slice(COMMAND_STORAGE_PREFIX.length));
      if (!Number.isFinite(id)) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      try {
        const command = JSON.parse(raw) as CommandStatus;
        if (command.status === "pending") out.set(id, command);
      } catch {
        continue;
      }
    }
  } catch {
    // Best-effort only, see loadPersistedCommand.
  }
  return out;
}

export function useCommandStatus(id: number | null): UseQueryResult<CommandStatus> {
  return useQuery<CommandStatus>({
    queryKey: ["command", id],
    queryFn: () => apiFetch<CommandStatus>(`/commands/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => {
      const data = query.state.data as CommandStatus | undefined;
      // Poll every 2 seconds while pending; stop once terminal (spec §9.4).
      if (data && TERMINAL.includes(data.status)) return false;
      return 2_000;
    },
  });
}