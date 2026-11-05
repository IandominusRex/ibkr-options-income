import type { components } from "@/lib/api-types";
import type { AssessedResponse } from "@/components/options/types";

/** The Top opportunities read contract, taken from the generated types (src/api/models/value.py). */
type Schemas = components["schemas"];

export type TopItem = Schemas["ValueTopItem"];
export type TopResponse = Schemas["ValueTopResponse"];
export type TopList = TopResponse["list_name"];

export type { AssessedResponse };

/** One labelled point on the bar. `names` has two entries when two levels sit at the same price. */
export type BarPoint = {
  kind: "price" | "fair" | "half" | "ceiling" | "stop";
  names: string[];
  value: number;
  /** 0-100, the point's place on the track. */
  pct: number;
  /** The label row it sits in (0 is the first row under the track). */
  lane: number;
  align: "start" | "center" | "end";
};

export type BarLayout = {
  points: BarPoint[];
  /** Levels the API has no number for, named so the card can show a hatched n/a. */
  unknown: string[];
  lanes: number;
};
