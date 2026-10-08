import { redirect } from "next/navigation";
import { sessionToken } from "@/lib/session";

const API_URL = process.env.STOCKBALL_API_URL ?? "http://localhost:8000";

export type Instrument = {
  id: string;
  player_id: string;
  symbol: string;
  display_name: string;
  player_name: string | null;
  player_club: string | null;
  player_position: string | null;
  current_price: string;
  reference_price: string;
  quantity_outstanding: string;
  net_shares_purchased: string;
  full_supply_price_multiplier: string;
  curve_depth_shares: string;
  price_change_24h: string;
  volume_24h: string;
  status: "ACTIVE" | "FROZEN" | "DELISTED";
  updated_at: string;
  /** Present on the instrument detail endpoint while the instrument is frozen. */
  freeze?: InstrumentFreeze | null;
  price_change_7d: string;
  /** Virtual pounds traded over the last 24 hours. */
  traded_value_24h: string;
  /** Why the instrument is frozen, when it is: MATCH_DAY, ADMIN_HALT or DATA_ISSUE. */
  freeze_reason: InstrumentFreeze["reason"] | null;
  /** Content-hash prefix of the stored player portrait; null when there is none. */
  player_image_version: string | null;
  /** Content-hash prefix of the stored club badge; null when there is none. */
  club_badge_version: string | null;
};

export type InstrumentFreeze = {
  reason: "MATCH_DAY" | "ADMIN_HALT" | "DATA_ISSUE";
  started_at: string;
  fixture_home_team: string | null;
  fixture_away_team: string | null;
  fixture_kickoff_at: string | null;
};

export type TraderKind = "PERSON" | "BOT";
export type LeaderboardFilter = "ALL" | "PEOPLE" | "BOTS";

export type TraderStanding = {
  account_id: string;
  display_name: string;
  kind: TraderKind;
  rank: number;
  net_worth: string;
  cash_balance: string;
  holdings_value: string;
  holdings_count: number;
  joined_at: string;
  /** Price movement of current holdings over the last 24 hours. */
  day_change: string;
  day_change_percent: string;
};

export type LeaderboardPage = {
  entries: TraderStanding[];
  total: number;
  limit: number;
  offset: number;
};

export type TraderHolding = {
  instrument_id: string;
  symbol: string;
  player_name: string;
  player_club: string | null;
  player_position: string | null;
  quantity: string;
  current_price: string;
  market_value: string;
  price_change_24h: string;
};

export type TraderTrade = {
  trade_id: string;
  instrument_id: string;
  player_name: string;
  side: OrderSide;
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
};

export type TraderProfile = {
  trader: TraderStanding;
  holdings: TraderHolding[];
  recent_trades: TraderTrade[];
};

export type PriceSnapshot = {
  id: string;
  instrument_id: string;
  old_price: string;
  new_price: string;
  captured_at: string;
};

export type PriceHistoryRange = "1D" | "1W" | "1M" | "3M" | "1Y" | "ALL";

export type Account = {
  id: string;
  email: string | null;
  display_name: string;
  account_type: "USER" | "ADMIN" | "SYNTHETIC_TRADER";
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  portfolio: {
    id: string;
    account_id: string;
    cash_balance: string;
    updated_at: string;
  };
};

export type Position = {
  id: string;
  portfolio_id: string;
  instrument_id: string;
  quantity: string;
  updated_at: string;
};

export type Portfolio = {
  id: string;
  account_id: string;
  cash_balance: string;
  updated_at: string;
  positions: Position[];
};

export type PortfolioActivity = {
  id: string;
  instrument_id: string;
  symbol: string;
  player_name: string;
  side: "BUY" | "SELL";
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
};

export type OrderSide = "BUY" | "SELL";

export type OrderQuote = {
  account_id: string;
  portfolio_id: string;
  instrument_id: string;
  side: OrderSide;
  quantity: string;
  execution_price: string;
  gross_amount: string;
  cash_balance_after: string;
  position_quantity_after: string;
  old_price: string;
  new_price: string;
  quoted_at: string;
};

export type OrderExecution = Omit<OrderQuote, "quoted_at"> & {
  request_id: string;
  order_id: string;
  trade_id: string;
  executed_at: string;
};

export type SparklineRange = "1D" | "1W";

export type FixtureStatus = "UPCOMING" | "PAUSED" | "LIVE" | "FINISHED" | "POSTPONED";

export type FixtureTeam = {
  team_id: string;
  name: string;
  short_name: string;
  /** The canonical club the FotMob team maps to, matching Instrument.player_club. */
  club: string | null;
  badge_version: string | null;
};

export type Fixture = {
  match_id: string;
  kickoff_at: string;
  /** When the clubs' players stop trading (the lineup lock). */
  lock_at: string;
  status: FixtureStatus;
  score: string | null;
  home: FixtureTeam;
  away: FixtureTeam;
};

export type RatedPlayer = {
  instrument_id: string;
  player_name: string;
  team_name: string;
  rating: string;
  goals: number;
  home_team: string;
  away_team: string;
  score: string | null;
};

export type Matchday = {
  lineup_lock_minutes: number;
  next_round: { season: number; round: number; fixtures: Fixture[] } | null;
  previous_round: number | null;
  top_rated: RatedPlayer[];
  /** Clubs in the current season's fixtures. */
  league_clubs: string[];
};

export type MarketTrade = {
  trade_id: string;
  executed_at: string;
  account_id: string;
  trader_name: string;
  trader_kind: TraderKind;
  strategy: string | null;
  side: OrderSide;
  shares: string;
  execution_price: string;
  gross_amount: string;
  instrument_id: string;
  player_name: string;
};

export type NewsItem = {
  document_id: string;
  title: string;
  url: string;
  source: string;
  published_at: string;
  topic: string | null;
  player_name: string;
  instrument_id: string;
};

export type TickerStock = {
  id: string;
  symbol: string;
  price: number;
  change: number;
};

export type RadarAxis = {
  label: string;
  score: number;
  value: string;
  components: Array<{
    label: string;
    score: number;
    value: string;
  }>;
};

export type PlayerStats = {
  season: number | null;
  games: number;
  starts: number;
  minutes: number;
  goals: number;
  assists: number;
  shots: number;
  shots_on_target: number;
  yellow_cards: number;
  red_cards: number;
  comparison_group: string;
  comparison_size: number;
  radar_axes: RadarAxis[];
};

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`Stockball API request failed (${status})`);
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await sessionToken();
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(8_000),
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let body: unknown;
    try { body = await response.json(); } catch { body = { message: response.statusText }; }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function getAccount(): Promise<Account> {
  try {
    return await apiRequest<Account>("/v1/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/login");
    throw error;
  }
}

export async function getOptionalAccount(): Promise<Account | null> {
  try {
    return await apiRequest<Account>("/v1/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function getInstruments(): Promise<Instrument[]> {
  return apiRequest<Instrument[]>("/v1/instruments");
}

export async function getPortfolio(portfolioId: string): Promise<Portfolio> {
  return apiRequest<Portfolio>(`/v1/portfolios/${portfolioId}`);
}

async function getPortfolioActivity(portfolioId: string): Promise<PortfolioActivity[]> {
  return apiRequest<PortfolioActivity[]>(`/v1/portfolios/${portfolioId}/activity?limit=20`);
}

export async function getPriceHistory(
  instrumentId: string,
  range: PriceHistoryRange = "ALL",
): Promise<PriceSnapshot[]> {
  return apiRequest<PriceSnapshot[]>(
    `/v1/instruments/${instrumentId}/price-history?range=${range}`,
  );
}

async function getPlayerStats(instrumentId: string): Promise<PlayerStats | null> {
  return apiRequest<PlayerStats | null>(`/v1/instruments/${instrumentId}/player-stats`);
}

export async function getSparklines(
  instrumentIds: string[],
  range: SparklineRange,
): Promise<Record<string, number[]>> {
  if (instrumentIds.length === 0) return {};
  const ids = encodeURIComponent(instrumentIds.join(","));
  const body = await apiRequest<{ series: Record<string, string[]> }>(
    `/v1/market/sparklines?range=${range}&ids=${ids}`,
  );
  return Object.fromEntries(
    Object.entries(body.series).map(([id, prices]) => [id, prices.map(Number)]),
  );
}

export async function getMatchday(): Promise<Matchday> {
  return apiRequest<Matchday>("/v1/market/matchday");
}

export async function getMarketTrades(limit = 5): Promise<MarketTrade[]> {
  return apiRequest<MarketTrade[]>(`/v1/market/trades?limit=${limit}`);
}

export async function getMarketNews(limit = 3): Promise<NewsItem[]> {
  return apiRequest<NewsItem[]>(`/v1/market/news?limit=${limit}`);
}

export async function getLeaderboard(
  filter: LeaderboardFilter,
  limit: number,
  offset = 0,
): Promise<LeaderboardPage> {
  return apiRequest<LeaderboardPage>(
    `/v1/traders/leaderboard?filter=${filter}&limit=${limit}&offset=${offset}`,
  );
}

export async function getPortfolioPageData() {
  const [account, instruments] = await Promise.all([getOptionalAccount(), getInstruments()]);
  if (!account) {
    return {
      account: null,
      instruments,
      portfolio: null,
      activity: [],
      tickerStocks: toTickerStocks(instruments),
      searchInstruments: instruments.filter((instrument) => instrument.status !== "DELISTED"),
    };
  }
  const [portfolio, activity] = await Promise.all([
    getPortfolio(account.portfolio.id),
    getPortfolioActivity(account.portfolio.id),
  ]);
  return { account, instruments, portfolio, activity, tickerStocks: toTickerStocks(instruments), searchInstruments: instruments.filter((instrument) => instrument.status !== "DELISTED") };
}

async function getInstrument(instrumentId: string): Promise<Instrument | null> {
  try {
    return await apiRequest<Instrument>(`/v1/instruments/${instrumentId}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
}

export async function getInstrumentPageData(instrumentId: string) {
  const [account, instruments, instrument] = await Promise.all([
    getOptionalAccount(),
    getInstruments(),
    getInstrument(instrumentId),
  ]);
  if (!instrument) return null;

  const [history, stats, portfolio] = await Promise.all([
    getPriceHistory(instrumentId, "1W"),
    getPlayerStats(instrumentId),
    account ? getPortfolio(account.portfolio.id) : Promise.resolve(null),
  ]);

  return {
    account,
    instrument,
    history,
    stats,
    portfolio,
    tickerStocks: toTickerStocks(instruments),
    searchInstruments: instruments.filter((candidate) => candidate.status !== "DELISTED"),
  };
}

export function shellData(account: Account | null, instruments: Instrument[]) {
  return {
    account,
    tickerStocks: toTickerStocks(instruments),
    searchInstruments: instruments.filter((instrument) => instrument.status !== "DELISTED"),
  };
}

async function getShellData() {
  const [account, instruments] = await Promise.all([getOptionalAccount(), getInstruments()]);
  return shellData(account, instruments);
}

export const LEADERBOARD_PAGE_SIZE = 50;

export async function getLeaderboardPageData(filter: LeaderboardFilter, page: number) {
  const offset = (page - 1) * LEADERBOARD_PAGE_SIZE;
  const [shell, leaderboard] = await Promise.all([
    getShellData(),
    getLeaderboard(filter, LEADERBOARD_PAGE_SIZE, offset),
  ]);
  // The signed-in trader's own standing, so they can find themselves on any page.
  const viewerStanding = shell.account ? await getTraderStanding(shell.account.id) : null;
  return { ...shell, leaderboard, viewerStanding };
}

async function getTraderStanding(accountId: string): Promise<TraderStanding | null> {
  try {
    return (await apiRequest<TraderProfile>(`/v1/traders/${encodeURIComponent(accountId)}`)).trader;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function getTraderPageData(accountId: string) {
  let profile: TraderProfile;
  try {
    profile = await apiRequest<TraderProfile>(`/v1/traders/${encodeURIComponent(accountId)}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
  return { ...(await getShellData()), profile };
}

export function playerName(instrument: Instrument): string {
  return instrument.player_name ?? instrument.display_name.replace(/\s+Share$/i, "");
}

function playerSymbol(instrument: Instrument): string {
  const words = playerName(instrument).trim().split(/\s+/);
  return (words.at(-1) ?? instrument.symbol).toUpperCase();
}

/**
 * Players in the market: trading now, or paused only for their match. Admin halts
 * (players who left the league) and delistings are left out of market-wide views.
 */
export function isInMarket(instrument: Instrument): boolean {
  return instrument.status === "ACTIVE"
    || (instrument.status === "FROZEN" && instrument.freeze_reason === "MATCH_DAY");
}

function toTickerStocks(instruments: Instrument[]): TickerStock[] {
  return [...instruments]
    .filter((instrument) => instrument.status !== "DELISTED")
    .sort((a, b) => Number(b.current_price) - Number(a.current_price))
    .slice(0, 20)
    .map((instrument) => ({
      id: instrument.id,
      symbol: playerSymbol(instrument),
      price: Number(instrument.current_price),
      change: Number(instrument.price_change_24h),
    }));
}
