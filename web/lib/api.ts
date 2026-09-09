const BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }
  // 204 No Content has nothing to parse - the caller's T is void for these
  // routes (watchlist remove, live-mode confirm). Every other 2xx the backend
  // emits carries a JSON body.
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}