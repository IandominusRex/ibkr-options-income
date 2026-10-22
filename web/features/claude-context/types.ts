import type { components } from "@/lib/api-types";

// Aliased from the generated OpenAPI schema (web/lib/api-types.ts, regenerated from
// docs/web/openapi.json) rather than hand-duplicated: src/api/models/claude_context.py is the
// source of truth. Python's list fields with a default come out optional in that file, so the
// page reads them through `?? []`.
type S = components["schemas"];

export type ClaudeContext = S["ClaudeContextResponse"];
export type MarketPicture = S["MarketPicture"];
export type RegimeState = S["RegimeState"];
export type IndexRegime = S["IndexRegime"];
export type MarketRegime = S["MarketRegime"];
export type RegimeLimit = S["RegimeLimitOut"];
export type LeveragedLimit = S["LeveragedLimitOut"];
export type CallContext = S["CallContextOut"];
export type Dropped = S["DroppedOut"];
export type Dossier = S["DossierOut"];
export type DossierEvent = S["DossierEvent"];
export type DossierReported = S["DossierReported"];
export type DossierFact = S["DossierFact"];
export type PictureStory = S["PictureStory"];
export type PictureFact = S["PictureFact"];
