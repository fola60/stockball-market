export const BANDS = {
  small: "Under 2%",
  medium: "2% to under 5%",
  large: "5% or more",
} as const;

export type Guess = { direction: "up" | "down"; band: keyof typeof BANDS };

export type Metric = { label: string; value: number; unit: "%" | "/ 90" };

export type Card = {
  position: string;
  chart: (number | null)[];
  form: {
    appearances: number;
    minutes_low: number;
    limited_minutes: boolean;
    rating: number | null;
    metrics: (Metric & { comparison: string | null })[];
  };
  trading: { buy_share_low: number | null; activity: string };
  match_status: string | null;
  attention: string | null;
};

export type Result = {
  instrument_id: string;
  name: string;
  club: string | null;
  cutoff: string;
  move: string;
  chart: (number | null)[];
  opening: string;
  closing: string;
  trading: { buys: string; sells: string; trades: number };
  form: {
    minutes: number;
    rating: number | null;
    metrics: Metric[];
    matches: {
      kickoff: string;
      opponent: string;
      minutes: number;
      rating: number | null;
      stats: Record<string, number>;
    }[];
  };
};

export type Round = {
  day: string;
  today: string;
  closes_at: string | null;
  state: "open" | "closed" | "unavailable";
  cards: Card[];
  weekly_topup: string;
  payout_percent: number[];
  pending_reward: string;
  entry: { guesses: Guess[]; score?: number; reward?: string; points?: number[] } | null;
  results: Result[] | null;
};
