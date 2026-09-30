import type { ProcessSnapshot, Summary } from "./types";

export const EMPTY_SUMMARY: Summary = {
  total_24h: 0,
  succeeded_24h: 0,
  failed_24h: 0,
  successful_items_24h: 0,
  failed_items_24h: 0,
  bot_statuses: {},
};
export const EMPTY_PROCESSES: ProcessSnapshot = {
  scheduler: { online: false, last_scheduled: [] },
  queued_jobs: [],
  processes: [],
};
export const INGEST_COMMANDS = [
  ["INGEST_PLAYERS", "Players", "Fetch and upsert league players"],
  ["INGEST_FIXTURES", "Fixtures", "Fetch fixtures for a league and season"],
  ["INGEST_PLAYER_STATS", "Player stats", "Fetch current player statistics"],
  ["IMPORT_MARKET_VALUES", "Market values", "Import Transfermarkt CSV files"],
  [
    "SEED_PLAYER_SHARES",
    "Player shares",
    "Create missing player-share instruments",
  ],
  [
    "INGEST_BETTING_MARKETS",
    "Betting markets",
    "Ingest Bet365 market observations",
  ],
  [
    "INGEST_TWITTER_INJURIES",
    "Injury reports",
    "Ingest configured injury-report query",
  ],
  [
    "INGEST_SOCIAL_FEEDS",
    "Social feeds",
    "Poll due sources, enrich articles, and classify sentiment",
  ],
] as const;
export const RUN_OPERATION_TYPES = [
  "INGEST_PLAYERS",
  "INGEST_FIXTURES",
  "INGEST_PLAYER_STATS",
  "IMPORT_MARKET_VALUES",
  "SEED_PLAYER_SHARES",
  "INGEST_BETTING_MARKETS",
  "INGEST_TWITTER_INJURIES",
  "INGEST_SOCIAL_FEEDS",
  "APPLY_TOPUPS",
  "TICK_SYNTHETIC_TRADERS",
  "CHECK_MARKET_FREEZES",
  "SPAWN_SYNTHETIC_TRADERS",
  "BOOTSTRAP_SYNTHETIC_PORTFOLIOS",
  "SET_SYNTHETIC_TRADER_STATUS",
] as const;
// Minute-by-minute schedules are hidden by default so they don't crowd out other runs.
export const DEFAULT_RUN_OPERATIONS = RUN_OPERATION_TYPES.filter(
  (operationType) =>
    operationType !== "TICK_SYNTHETIC_TRADERS" && operationType !== "CHECK_MARKET_FREEZES",
);
