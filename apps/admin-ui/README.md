# Stockball admin

Internal operations console for data ingestion and synthetic traders. The UI talks only to the API's `/internal/v1/admin` endpoints; it does not access Postgres, Redis, or the trading engine directly.

```bash
npm install
NEXT_PUBLIC_STOCKBALL_API_URL=http://localhost:8000 npm run dev
```

Enable the API endpoints with `STOCKBALL_ADMIN_API_ENABLED=true`.
