# Content Fetching

`ContentFetchService` is the worker's provider-neutral, read-only boundary for fetching
content from explicitly approved URLs. It is deliberately not a scraper, parser,
repository, queue consumer, or strategy component.

## Contract

Callers create a typed `FetchRequest` with an exact host allowlist. The service performs
one bounded `GET`, manually follows only allowlisted redirects, and returns typed
`FetchedContent` bytes plus response metadata. It does not persist content.

For pages that need a signed-in, rendered browser session, configure the optional browser
fallback with Chrome's root user-data directory and a named profile directory. The service
passes the latter as Chrome's `--profile-directory` argument; do not pass a profile path as
the user-data directory.

When no user-data directory or profile is configured, ChromeDriver creates an isolated
temporary profile for the browser session. This is preferred for public pages that do not
need persistent login, consent, or locale state.

Chrome locks an active user-data directory. The fetcher refuses to launch against a locked
profile instead of opening an uncontrolled window. Fully quit that Chrome instance first,
or use a dedicated persistent Chrome user-data directory for worker ingestion.

For local Twitter testing, initialize the dedicated profile once, sign into X, and close
that dedicated Chrome window before running the fetch:

```bash
python -m scripts.open_chrome_profile --dedicated-profile --url https://x.com/home
python -m scripts.test_twitter_search "arsenal XI"
```

Set `FetchRequest.prefer_browser=True` only for providers whose ordinary HTTP response
is known to be an unusable JavaScript shell. It uses the browser path when browser support
is enabled; otherwise the normal bounded HTTP path remains available.

Provider clients that must click client-side navigation may use `browser_session`. The
session validates every opened and resulting top-level URL against the same host allowlist,
and bounds rendered page source to 15 MB by default. Provider-specific selectors and click
sequences remain in the provider module.

```python
from app.ingestion.fetch import ContentFetchService, FetchRequest

content = ContentFetchService().fetch(
    FetchRequest(
        url="https://example.org/news/player-update",
        allowed_hosts=("example.org",),
    )
)
html = content.text()
```

## Safety Boundaries

- Callers must provide `allowed_hosts`; unrestricted URL fetching is rejected.
- Only absolute `http` and `https` URLs are supported; embedded URL credentials are rejected.
- Redirect targets are checked against the same allowlist.
- Default response limit is 2 MB and default redirect limit is three.
- Provider modules own authentication, robots/terms compliance, parsing, caching,
  persistence, and provider-specific retries.
- This service does not mutate prices, positions, trades, orders, or strategy state.
