# Stockball dev portal

Local-only operations console for data ingestion and synthetic traders. The UI talks only to the API's `/internal/v1/dev` endpoints; it does not access Postgres, Redis, or the trading engine directly.

```bash
npm install
NEXT_PUBLIC_STOCKBALL_API_URL=http://localhost:8000 npm run dev -- --port 3001
```

Enable the API endpoints with `STOCKBALL_DEV_PORTAL_ENABLED=true`.
