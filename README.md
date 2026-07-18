# stockball-market

## Local Ingestion

Run one-off ingestion commands against local services without Docker:

```bash
scripts/local-ingestion.sh setup
scripts/local-ingestion.sh migrate
scripts/local-ingestion.sh players
scripts/local-ingestion.sh fixtures --from-date 2025-08-01 --to-date 2025-08-31
scripts/local-ingestion.sh stats --stat-type standard --stat-type shooting
scripts/local-ingestion.sh market-values
scripts/local-ingestion.sh shares
scripts/local-ingestion.sh twitter-sources --registry /path/to/reviewed-registry.json
scripts/local-ingestion.sh twitter-injuries
```

For overrides:

```bash
cp scripts/local-ingestion.env.example .env.local-ingestion
```

The `migrate` command expects a local Postgres database matching `STOCKBALL_WORKER_DATABASE_URL` to already exist.

More detail is in `services/worker/README.md`.
The Twitter injury pipeline is opt-in; its complete operational and policy contract is in
`services/worker/app/ingestion/social/twitter/README.md`.
