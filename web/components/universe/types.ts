// Shared types for the universe edit UI (M7 Task 7.5), matching the response
// shapes in src/api/routers/universe.py. Kept inline rather than generated
// for the same reason as components/options/types.ts: the route is new and
// `npm run gen:api` will pick it up on the next regeneration pass.

export type UniverseEntry = {
  symbol: string;
  overridden: boolean;
  removed: boolean;
  created_by: string | null;
  created_at: string | null;
};

export type UniverseListOut = {
  name: string;
  overridable: boolean;
  entries: UniverseEntry[];
};

export type UniverseResponse = {
  as_of: string;
  lists: UniverseListOut[];
  sectors: Record<string, string>;
  strike_bands: Record<string, number>;
  editable: boolean;
};
