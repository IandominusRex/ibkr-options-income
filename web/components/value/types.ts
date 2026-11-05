import type { components } from "@/lib/api-types";

/** The value book's read contract, taken from the generated types (src/api/models/value.py). */
type Schemas = components["schemas"];

export type ValueBook = Schemas["ValueBookResponse"];
export type ValuePosition = Schemas["ValuePositionOut"];
export type ValuePositionsResponse = Schemas["ValuePositionsResponse"];
export type ValueProposal = Schemas["ValueProposalOut"];
export type ValueFunding = Schemas["ValueFundingOut"];
export type ValueBreakers = Schemas["ValueBreakersOut"];
export type ValueNextExit = Schemas["ValueNextExit"];

/** The fields a decision needs from a proposal: what the confirm sentence names and what the tap carries back. */
export type ValueProposalLike = Pick<
  ValueProposal,
  "id" | "kind" | "symbol" | "shares" | "price" | "cause" | "status" | "fingerprint"
>;
