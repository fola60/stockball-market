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
  price_change_24h: string;
  volume_24h: string;
  status: "ACTIVE" | "FROZEN" | "DELISTED";
  updated_at: string;
  /** Present on the instrument detail endpoint while the instrument is frozen. */
  freeze?: InstrumentFreeze | null;
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

export type MarketRow = {
  instrument: Instrument;
  directionRank: number;
  prices: number[];
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

export async function getMarketPageData() {
  const [account, instruments] = await Promise.all([getOptionalAccount(), getInstruments()]);
  const tradable = instruments.filter((instrument) => instrument.status !== "DELISTED");
  const byChange = [...tradable].sort(
    (a, b) => Number(b.price_change_24h) - Number(a.price_change_24h),
  );
  const gainers = byChange.filter((instrument) => Number(instrument.price_change_24h) >= 0).slice(0, 5);
  const mostValuable = [...tradable]
    .sort(
      (a, b) =>
        Number(b.current_price) * Number(b.quantity_outstanding)
        - Number(a.current_price) * Number(a.quantity_outstanding),
    )
    .slice(0, 80);
  const decliners = mostValuable
    .filter((instrument) => Number(instrument.price_change_24h) < 0)
    .sort((a, b) => Number(a.price_change_24h) - Number(b.price_change_24h))
    .slice(0, 5);

  const selected = gainers.flatMap((instrument, index) => {
    const rows = [{ instrument, directionRank: index + 1 }];
    if (decliners[index]) rows.push({ instrument: decliners[index], directionRank: index + 1 });
    return rows;
  });

  // Keep the market-page fan-out below the API's database pool limit. These
  // queries are intentionally sequential: the list is capped at ten rows and
  // a partial pool exhaustion would make the entire authenticated page fail.
  const histories: PriceSnapshot[][] = [];
  for (const { instrument } of selected) {
    histories.push(await getPriceHistory(instrument.id, "1D"));
  }

  const rows: MarketRow[] = selected.map((row, index) => ({
    ...row,
    prices: chartPrices(histories[index], Number(row.instrument.current_price)),
  }));

  const tickerStocks = toTickerStocks(tradable);

  const updatedAt = tradable.reduce(
    (latest, instrument) => instrument.updated_at > latest ? instrument.updated_at : latest,
    tradable[0]?.updated_at ?? new Date().toISOString(),
  );

  return { account, rows, tickerStocks, searchInstruments: tradable, updatedAt };
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

async function getShellData() {
  const [account, instruments] = await Promise.all([getOptionalAccount(), getInstruments()]);
  return {
    account,
    tickerStocks: toTickerStocks(instruments),
    searchInstruments: instruments.filter((instrument) => instrument.status !== "DELISTED"),
  };
}

export const LEADERBOARD_PAGE_SIZE = 50;

export async function getLeaderboardPageData(filter: LeaderboardFilter, page: number) {
  const offset = (page - 1) * LEADERBOARD_PAGE_SIZE;
  const [shell, leaderboard] = await Promise.all([
    getShellData(),
    apiRequest<LeaderboardPage>(
      `/v1/traders/leaderboard?filter=${filter}&limit=${LEADERBOARD_PAGE_SIZE}&offset=${offset}`,
    ),
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

function chartPrices(history: PriceSnapshot[], currentPrice: number): number[] {
  const cutoff = Date.now() - 24 * 60 * 60 * 1_000;
  const chronological = history
    .filter((snapshot) => new Date(snapshot.captured_at).getTime() >= cutoff)
    .sort((a, b) => a.captured_at.localeCompare(b.captured_at))
    .map((snapshot) => Number(snapshot.new_price))
    .filter(Number.isFinite);

  const recent = chronological.slice(-18);
  if (recent.at(-1) !== currentPrice) recent.push(currentPrice);
  return recent.length > 1 ? recent : [currentPrice, currentPrice];
}
