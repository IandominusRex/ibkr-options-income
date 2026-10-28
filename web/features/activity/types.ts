import type { components } from "@/lib/api-types";

type S = components["schemas"];

/** Aliases of the generated contract (docs/web/openapi.json), never hand-copied. */
export type SizingGroup = S["SizingGroupOut"];
export type SizingRecordResponse = S["SizingRecordResponse"];
export type LedgerExecution = S["LedgerExecutionRowOut"];
export type LedgerExecutionsResponse = S["LedgerExecutionsResponse"];
export type SpreadOrder = S["SpreadOrderOut"];
export type SpreadOrdersResponse = S["SpreadOrdersResponse"];
