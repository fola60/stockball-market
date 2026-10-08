// Shared by the server page and the client filters, so it must not be a client module.
export const SORTS = {
  value: "Market value",
  day: "24h change",
  week: "7-day change",
  traded: "Traded 24h",
} as const;

export type PlayersSort = keyof typeof SORTS;
export const POSITIONS = ["GK", "DF", "MF", "FW"] as const;
export type Position = (typeof POSITIONS)[number];

export type PlayersQuery = { club: string | null; position: Position | null; sort: PlayersSort };

export function playersHref(query: PlayersQuery, page = 1): string {
  const params = new URLSearchParams();
  if (query.club) params.set("club", query.club);
  if (query.position) params.set("position", query.position);
  if (query.sort !== "value") params.set("sort", query.sort);
  if (page > 1) params.set("page", String(page));
  const search = params.toString();
  return search ? `/players?${search}` : "/players";
}
