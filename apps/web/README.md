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
