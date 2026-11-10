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

/** Image versions for a revealed player's portrait and club badge. */
export type Media = { player_image_version: string | null; club_badge_version: string | null };

export type Round = {
  day: string;
  today: string;
  closes_at: string | null;
  state: "open" | "closed" | "unavailable";
  cards: Card[];
  weekly_topup: string;
  payout_percent: number[];
  pending_reward: string;
  /** One slot per player; null until that player is called. */
  entry: {
    guesses: (Guess | null)[];
    points: (number | null)[];
    score: number | null;
    reward: string | null;
  } | null;
  /** Every player once the round closes; before that, only the players this account has called. */
  results: (Result | null)[] | null;
};

/** The API's answer to one call: that player revealed, plus the entry so far. */
export type Called = {
  slot: number;
  guesses: (Guess | null)[];
  points: (number | null)[];
  result: Result;
  score: number | null;
  reward: string | null;
};
