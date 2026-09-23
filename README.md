# stockball-market

## Docker Compose environments

The base `docker-compose.yml` contains settings shared by every environment. Pair it with
exactly one environment overlay.

For local development, build the images from the working tree and publish the service ports:

```bash
docker compose -f docker-compose.yml -f compose.dev.yml up --build
```

Compose applies tracked database migrations before starting the trading engine and application
services. You can also run the migrator explicitly and safely more than once:

```bash
docker compose -f docker-compose.yml -f compose.dev.yml run --rm migrate
```

For production, use pre-built images, keep backend services private, and expose the public web
application through Caddy:

```bash
POSTGRES_PASSWORD='replace-with-a-strong-secret' \
IMAGE_TAG='full-git-commit-sha' \
DOMAIN='stockball.example.com' \
docker compose -f docker-compose.yml -f compose.prod.yml up -d
```

For production deployments, run the migration service after pulling images and before updating
the application containers:

```bash
POSTGRES_PASSWORD='replace-with-a-strong-secret' \
IMAGE_TAG='full-git-commit-sha' \
DOMAIN='stockball.example.com' \
docker compose -f docker-compose.yml -f compose.prod.yml run --rm migrate
```

Production publishes Caddy on ports 80 and 443. The API and admin UI bind only to the host's
loopback interface for access through an SSH tunnel. PostgreSQL, Redis, the trading engine, and
the public web container have no host ports.

Validate the fully merged configuration before starting it:

```bash
docker compose -f docker-compose.yml -f compose.dev.yml config --quiet

POSTGRES_PASSWORD='validation-only' \
IMAGE_TAG='validation-only' \
DOMAIN='example.com' \
docker compose -f docker-compose.yml -f compose.prod.yml config --quiet
```

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

## CI/CD

Pull requests and pushes to `main` run the complete test suite. After a successful `main` build,
GitHub Actions publishes five `linux/amd64` images to GHCR with the full commit SHA as the image
tag. The production job then uploads the deployment manifests and scripts to `/opt/stockball` and
runs `scripts/deploy-production.sh` over SSH.

The deployment script serializes releases with `flock`, pulls every image before changing the
running application, backs up an existing database, applies tracked migrations, updates the stack,
and verifies both the API and public HTTPS endpoint. A failed health check restores the previous
application image tag. Database migrations are not reversed, so migrations must remain compatible
with the previous application release.

Configure a GitHub `production` environment with these secrets:

- `VPS_HOST`: the VPS IP address.
- `VPS_USER`: the dedicated `deploy` user.
- `VPS_SSH_PRIVATE_KEY`: the dedicated deployment private key.
- `VPS_SSH_KNOWN_HOSTS`: the verified VPS SSH host-key entry.

Set `PRODUCTION_URL` to the public HTTPS URL and leave `DEPLOY_ENABLED` unset while preparing the
server. Pushes to `main` will still test and publish images, but the deployment job remains skipped.
Set `DEPLOY_ENABLED=true` only after DNS, VPS configuration, environment secrets, and GHCR access
have been verified. Private GHCR packages require the `deploy` user to log in to `ghcr.io` once
with a token containing `read:packages`.

The repository includes a daily local backup timer. Install it on the VPS after the first release:

```bash
sudo install -m 0644 /opt/stockball/infra/systemd/stockball-backup.service /etc/systemd/system/
sudo install -m 0644 /opt/stockball/infra/systemd/stockball-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stockball-backup.timer
```

Backups are stored in `/opt/stockball/backups` with mode `0600` and retained for 14 days by
default. Set `BACKUP_RETENTION_DAYS` in `/opt/stockball/.env` to change local retention. Copy these
backups to separately managed off-server storage and test restoring them before treating the backup
process as complete.
