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

const TERMINAL: CommandStatus["status"][] = ["applied", "failed", "expired"];

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