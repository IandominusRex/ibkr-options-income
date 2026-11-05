import type { components } from "@/lib/api-types";

/** The ticker file's read contract, taken from the generated types (src/api/models/value.py). */
type Schemas = components["schemas"];

export type ValueTicker = Schemas["ValueTickerResponse"];
export type ValueFile = Schemas["ValueFileOut"];
export type ValueList = Schemas["ValueListOut"];
export type ValueGate = Schemas["ValueGateOut"];
export type ValueMethod = Schemas["ValueMethodOut"];
export type ValueClaude = Schemas["ValueClaudeOut"];
export type ValueClaudeList = Schemas["ValueClaudeListOut"];
export type ValueDriver = Schemas["ValueDriverOut"];
export type ValueNote = Schemas["ValueNoteOut"];
export type ValueKillTrigger = Schemas["ValueKillTriggerOut"];
export type ValueFact = Schemas["ValueFactOut"];
export type ValueReevaluation = Schemas["ValueReevaluationOut"];
export type ValuePlan = Schemas["ValuePlanOut"];

/** One piece of a sentence: unknown pieces are drawn hatched, never as a zero. */
export type Segment = { text: string; unknown?: boolean };

/** When the block asks again, and why: the file is being worked out, or a Claude read is awaited. */
export type Watch = { since: number; readAt: string | null };
