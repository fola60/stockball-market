# Stockball web

The customer-facing Stockball market and portfolio frontend. It is a standard
Next.js application and reads live market/account data from the Stockball API,
which remains the boundary in front of PostgreSQL.

## Configuration

Copy `.env.example` to `.env.local` when running outside Docker:

```bash
cp .env.example .env.local
```

- `STOCKBALL_API_URL` is the server-side URL for `services/api`.
- The market and player pages are public. Sign-in and account creation open in
  a modal when a guest chooses to trade or view a portfolio. The web app stores
  the opaque API session token in a secure, HttpOnly cookie.
- Daily Games is available at `/daily-games` (`/blind-market` redirects there).
  It requires migration 0041 and enough trade history and timestamped match
  observations to generate three replays. The API, tables and settings keep
  their original `blind_market` names. Each card is revealed as soon as it is
  called, and the reward can be claimed once all three are called. Rounds close
  at midnight Dublin time. Set
  `STOCKBALL_BLIND_MARKET_WEEKLY_TOPUP` on the API to the virtual-cash amount a
  perfect score should earn (default: `100000.0000`). The amount is fixed for
  the week when its first round is created.

## Run locally

```bash
npm install
npm run dev
```

The frontend runs on [http://localhost:3002](http://localhost:3002) so port
3000 remains available for the trading engine. The API must be available at the
configured URL (default: `http://localhost:8000`).

## Checks

```bash
npm test
```
