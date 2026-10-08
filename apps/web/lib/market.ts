import {
  getInstruments,
  getLeaderboard,
  getMarketNews,
  getMarketTrades,
  getMatchday,
  getOptionalAccount,
  getPortfolio,
  getSparklines,
  isInMarket,
  playerName,
  shellData,
  type Fixture,
  type FixtureTeam,
  type Instrument,
  type LeaderboardPage,
  type MarketTrade,
  type Matchday,
  type NewsItem,
  type Portfolio,
} from "./api";
import { direction } from "./format";

export type MoverRow = {
  instrument: Instrument;
  name: string;
  change: number;
  fullyHeld: boolean;
  prices: number[];
};

export type Movers = { risers: MoverRow[]; fallers: MoverRow[] };

export type ClubTile = {
  club: string;
  team: FixtureTeam | null;
  marketValue: number;
  change1d: number;
  change7d: number;
  players: { id: string; name: string; change1d: number; change7d: number }[];
};

export type FixtureMarket = {
  fixture: Fixture;
  /** Market value of both clubs' players in the market. */
  marketValue: number;
  homeStar: Instrument | null;
  awayStar: Instrument | null;
  /** The signed-in trader's holdings in the two clubs. */
  holdings: { names: string[]; value: number };
};

export type PortfolioSummary = {
  netWorth: number;
  cash: number;
  dayPnl: number;
  dayPercent: number;
  best: { instrument: Instrument; change: number } | null;
  exposure: { fixture: Fixture; share: number } | null;
};

const MOVERS_PER_SIDE = 6;

export const marketValue = (instrument: Instrument) =>
  Number(instrument.current_price) * Number(instrument.quantity_outstanding);

/** Every share has been bought, so the price can only move when a holder sells. */
export const isFullyHeld = (instrument: Instrument) =>
  Number(instrument.quantity_outstanding) > 0
  && Number(instrument.net_shares_purchased) >= Number(instrument.quantity_outstanding) * 0.9999;

/** A secondary module's failure should leave the rest of the page standing. */
async function optional<T>(request: Promise<T>, fallback: T): Promise<T> {
  try {
    return await request;
  } catch {
    return fallback;
  }
}

/** Risers and fallers, counting only moves that show at the displayed precision. */
function selectMovers(instruments: Instrument[], change: (instrument: Instrument) => number, decimals: number) {
  const ranked = instruments.map((instrument) => ({ instrument, change: change(instrument) }));
  return {
    risers: ranked.filter((row) => direction(row.change, decimals) > 0).sort((a, b) => b.change - a.change).slice(0, MOVERS_PER_SIDE),
    fallers: ranked.filter((row) => direction(row.change, decimals) < 0).sort((a, b) => a.change - b.change).slice(0, MOVERS_PER_SIDE),
  };
}

function withPrices(
  selection: ReturnType<typeof selectMovers>,
  series: Record<string, number[]>,
): Movers {
  const row = ({ instrument, change }: { instrument: Instrument; change: number }): MoverRow => ({
    instrument,
    name: playerName(instrument),
    change,
    fullyHeld: isFullyHeld(instrument),
    prices: series[instrument.id] ?? [Number(instrument.current_price)],
  });
  return { risers: selection.risers.map(row), fallers: selection.fallers.map(row) };
}

/** Cap-weighted change: today's value against the value implied by each opening price. */
function weightedChange(instruments: Instrument[], change: (instrument: Instrument) => number) {
  let now = 0;
  let before = 0;
  for (const instrument of instruments) {
    const value = marketValue(instrument);
    const factor = 1 + change(instrument) / 100;
    now += value;
    before += factor > 0 ? value / factor : value;
  }
  return before > 0 ? (now / before - 1) * 100 : 0;
}

function clubTiles(instruments: Instrument[], matchday: Matchday | null): ClubTile[] {
  const teams = new Map<string, FixtureTeam>();
  for (const fixture of matchday?.next_round?.fixtures ?? []) {
    for (const team of [fixture.home, fixture.away]) if (team.club) teams.set(team.club, team);
  }
  const leagueClubs = new Set(matchday?.league_clubs ?? []);
  const byClub = new Map<string, Instrument[]>();
  for (const instrument of instruments) {
    const club = instrument.player_club;
    if (!club || (leagueClubs.size > 0 && !leagueClubs.has(club))) continue;
    byClub.set(club, [...(byClub.get(club) ?? []), instrument]);
  }
  return [...byClub.entries()]
    .map(([club, members]) => ({
      club,
      team: teams.get(club) ?? null,
      marketValue: members.reduce((total, instrument) => total + marketValue(instrument), 0),
      change1d: weightedChange(members, (instrument) => Number(instrument.price_change_24h)),
      change7d: weightedChange(members, (instrument) => Number(instrument.price_change_7d)),
      players: [...members]
        .sort((a, b) => marketValue(b) - marketValue(a))
        .slice(0, 3)
        .map((instrument) => ({
          id: instrument.id,
          name: playerName(instrument).split(" ").at(-1) ?? playerName(instrument),
          change1d: Number(instrument.price_change_24h),
          change7d: Number(instrument.price_change_7d),
        })),
    }))
    .sort((a, b) => b.marketValue - a.marketValue);
}

function fixtureMarkets(
  matchday: Matchday | null,
  instruments: Instrument[],
  holdings: { instrument: Instrument; value: number }[],
): FixtureMarket[] {
  const byClub = new Map<string, Instrument[]>();
  for (const instrument of instruments) {
    if (instrument.player_club) {
      byClub.set(instrument.player_club, [...(byClub.get(instrument.player_club) ?? []), instrument]);
    }
  }
  const star = (team: FixtureTeam) =>
    [...(team.club ? byClub.get(team.club) ?? [] : [])].sort((a, b) => marketValue(b) - marketValue(a))[0] ?? null;
  return (matchday?.next_round?.fixtures ?? []).map((fixture) => {
    const clubs = new Set([fixture.home.club, fixture.away.club].filter(Boolean));
    const held = holdings.filter((holding) => clubs.has(holding.instrument.player_club));
    return {
      fixture,
      marketValue: [...clubs].reduce(
        (total, club) => total + (byClub.get(club as string) ?? []).reduce((sum, instrument) => sum + marketValue(instrument), 0),
        0,
      ),
      homeStar: star(fixture.home),
      awayStar: star(fixture.away),
      holdings: {
        names: held.sort((a, b) => b.value - a.value).map((holding) => playerName(holding.instrument)),
        value: held.reduce((total, holding) => total + holding.value, 0),
      },
    };
  });
}

function summarisePortfolio(
  portfolio: Portfolio,
  holdings: { instrument: Instrument; value: number; quantity: number }[],
  fixtures: FixtureMarket[],
): PortfolioSummary {
  const invested = holdings.reduce((total, holding) => total + holding.value, 0);
  const cash = Number(portfolio.cash_balance);
  const dayPnl = holdings.reduce((total, holding) => {
    const factor = 1 + Number(holding.instrument.price_change_24h) / 100;
    return total + (factor > 0 ? holding.value - holding.value / factor : 0);
  }, 0);
  const netWorth = cash + invested;
  const best = [...holdings]
    .map((holding) => ({ instrument: holding.instrument, change: Number(holding.instrument.price_change_24h) }))
    .sort((a, b) => b.change - a.change)[0] ?? null;
  const exposed = fixtures
    .filter((market) => market.fixture.status !== "FINISHED" && market.fixture.status !== "POSTPONED" && market.holdings.value > 0)
    .sort((a, b) => b.holdings.value - a.holdings.value)[0];
  return {
    netWorth,
    cash,
    dayPnl,
    dayPercent: netWorth - dayPnl > 0 ? (dayPnl / (netWorth - dayPnl)) * 100 : 0,
    best,
    exposure: exposed && invested > 0 ? { fixture: exposed.fixture, share: (exposed.holdings.value / invested) * 100 } : null,
  };
}

export async function getHomePageData() {
  const [account, instruments, matchday] = await Promise.all([
    getOptionalAccount(),
    getInstruments(),
    optional<Matchday | null>(getMatchday(), null),
  ]);
  const market = instruments.filter(isInMarket);

  const daySelection = selectMovers(market, (instrument) => Number(instrument.price_change_24h), 2);
  const weekSelection = selectMovers(market, (instrument) => Number(instrument.price_change_7d), 1);
  const listed = instruments.filter((instrument) => instrument.status !== "DELISTED");
  // The "All players" preview is the first page of /players, which includes paused players.
  const valuable = [...listed].sort((a, b) => marketValue(b) - marketValue(a)).slice(0, 8);
  const ids = (selection: ReturnType<typeof selectMovers>) =>
    [...selection.risers, ...selection.fallers].map((row) => row.instrument.id);

  // The API's connection pool refuses work when exhausted rather than queueing it,
  // so secondary requests go out a few at a time.
  const [daySeries, weekSeries, trades] = await Promise.all([
    optional(getSparklines(ids(daySelection), "1D"), {}),
    optional(getSparklines([...new Set([...ids(weekSelection), ...valuable.map((instrument) => instrument.id)])], "1W"), {}),
    optional<MarketTrade[]>(getMarketTrades(5), []),
  ]);
  const [news, leaders, people, portfolio] = await Promise.all([
    optional<NewsItem[]>(getMarketNews(3), []),
    optional<LeaderboardPage | null>(getLeaderboard("ALL", 5), null),
    optional<LeaderboardPage | null>(getLeaderboard("PEOPLE", 1), null),
    account ? optional<Portfolio | null>(getPortfolio(account.portfolio.id), null) : Promise.resolve(null),
  ]);

  const byId = new Map(instruments.map((instrument) => [instrument.id, instrument]));
  const holdings = (portfolio?.positions ?? []).flatMap((position) => {
    const instrument = byId.get(position.instrument_id);
    const quantity = Number(position.quantity);
    return instrument && quantity > 0 ? [{ instrument, quantity, value: quantity * Number(instrument.current_price) }] : [];
  });
  const fixtures = fixtureMarkets(matchday, market, holdings);
  const lastTrade = instruments.reduce(
    (latest, instrument) => (instrument.updated_at > latest ? instrument.updated_at : latest),
    instruments[0]?.updated_at ?? new Date().toISOString(),
  );

  return {
    ...shellData(account, instruments),
    lastTrade,
    tradingCount: market.length,
    pausedCount: listed.length - market.length,
    listedCount: listed.length,
    movers: {
      day: withPrices(daySelection, daySeries),
      week: withPrices(weekSelection, weekSeries),
    },
    matchday,
    fixtures,
    clubs: clubTiles(market, matchday),
    mostTraded: [...market]
      .filter((instrument) => Number(instrument.traded_value_24h) > 0)
      .sort((a, b) => Number(b.traded_value_24h) - Number(a.traded_value_24h))
      .slice(0, 5),
    topRated: (matchday?.top_rated ?? []).flatMap((rated) => {
      const instrument = byId.get(rated.instrument_id);
      return instrument ? [{ rated, instrument }] : [];
    }),
    trades,
    leaders: leaders?.entries ?? [],
    peopleOnBoard: people?.total ?? 0,
    valuable: valuable.map((instrument) => ({ instrument, prices: weekSeries[instrument.id] ?? [] })),
    news: news.flatMap((item) => {
      const instrument = byId.get(item.instrument_id);
      return instrument ? [{ item, instrument }] : [];
    }),
    portfolio: portfolio ? summarisePortfolio(portfolio, holdings, fixtures) : null,
  };
}

export type HomePageData = Awaited<ReturnType<typeof getHomePageData>>;
