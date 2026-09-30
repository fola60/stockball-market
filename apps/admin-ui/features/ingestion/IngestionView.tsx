import { useCallback, useState } from "react";
import { Play, RefreshCw } from "lucide-react";

import { Field } from "../../components/ui";
import { INGEST_COMMANDS } from "../../lib/constants";
import { getJson } from "../../lib/api";
import { formatNumber, label, time } from "../../lib/format";
import type { SocialIngestionSummary } from "../../lib/types";

export function IngestionView({
  enqueue,
  busy,
}: {
  enqueue: (a: string, b?: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const [selected, setSelected] = useState("INGEST_PLAYERS");
  const [league, setLeague] = useState("9"),
    [season, setSeason] = useState("2025");
  const [values, setValues] = useState("/data/market-values/valuations.csv"),
    [players, setPlayers] = useState("");
  const [mode, setMode] = useState("PRE_MATCH"),
    [queryKey, setQueryKey] = useState("");
  const [socialProvider, setSocialProvider] = useState("ALL"),
    [socialLimit, setSocialLimit] = useState("100");
  const [socialStatus, setSocialStatus] = useState<SocialIngestionSummary | null>(
    null,
  );
  const [statusError, setStatusError] = useState("");
  const [statusLoading, setStatusLoading] = useState(false);
  const command = INGEST_COMMANDS.find((item) => item[0] === selected)!;

  const loadSocialStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      setSocialStatus(
        await getJson<SocialIngestionSummary>(
          "/internal/v1/admin/social-ingestion",
        ),
      );
      setStatusError("");
    } catch (caught) {
      setStatusError(
        caught instanceof Error ? caught.message : "Social status unavailable",
      );
    } finally {
      setStatusLoading(false);
    }
  }, []);

  function submit() {
    const base = { league: Number(league), season: Number(season) };
    let p: Record<string, unknown> = base;
    if (selected === "IMPORT_MARKET_VALUES")
      p = { valuations_csv: values, players_csv: players };
    if (selected === "INGEST_BETTING_MARKETS")
      p = { league: "Premier League", mode };
    if (selected === "INGEST_TWITTER_INJURIES") p = { query_key: queryKey };
    if (selected === "INGEST_SOCIAL_FEEDS")
      p = { provider: socialProvider, limit: Number(socialLimit) };
    if (selected === "SEED_PLAYER_SHARES") p = {};
    enqueue(selected, p);
  }
  return (
    <div className="twoCol">
      <section className="commandList">
        <h2>Commands</h2>
        {INGEST_COMMANDS.map((item) => (
          <button
            key={item[0]}
            className={selected === item[0] ? "command selected" : "command"}
            onClick={() => {
              setSelected(item[0]);
              if (item[0] === "INGEST_SOCIAL_FEEDS" && socialStatus === null) {
                void loadSocialStatus();
              }
            }}
          >
            <strong>{item[1]}</strong>
            <small>{item[2]}</small>
          </button>
        ))}
      </section>
      <section className="formPanel">
        <h2>{command[1]}</h2>
        <p>{command[2]}</p>
        {![
          "IMPORT_MARKET_VALUES",
          "SEED_PLAYER_SHARES",
          "INGEST_BETTING_MARKETS",
          "INGEST_TWITTER_INJURIES",
          "INGEST_SOCIAL_FEEDS",
        ].includes(selected) && (
          <div className="formGrid">
            <Field label="League">
              <input
                value={league}
                onChange={(e) => setLeague(e.target.value)}
                type="number"
              />
            </Field>
            <Field label="Season">
              <input
                value={season}
                onChange={(e) => setSeason(e.target.value)}
                type="number"
              />
            </Field>
          </div>
        )}
        {selected === "IMPORT_MARKET_VALUES" && (
          <>
            <Field label="Valuations CSV path">
              <input
                value={values}
                onChange={(e) => setValues(e.target.value)}
              />
            </Field>
            <Field label="Players CSV path (optional)">
              <input
                value={players}
                onChange={(e) => setPlayers(e.target.value)}
              />
            </Field>
          </>
        )}
        {selected === "INGEST_BETTING_MARKETS" && (
          <Field label="Mode">
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option>PRE_MATCH</option>
              <option>LIVE</option>
            </select>
          </Field>
        )}
        {selected === "INGEST_TWITTER_INJURIES" && (
          <Field label="Query key (optional)">
            <input
              value={queryKey}
              onChange={(e) => setQueryKey(e.target.value)}
            />
          </Field>
        )}
        {selected === "INGEST_SOCIAL_FEEDS" && (
          <>
            <div className="formGrid">
              <Field label="Provider">
                <select
                  value={socialProvider}
                  onChange={(event) => setSocialProvider(event.target.value)}
                >
                  <option value="ALL">All providers</option>
                  <option value="RSS">RSS</option>
                  <option value="BLUESKY">Bluesky</option>
                  <option value="MASTODON">Mastodon</option>
                </select>
              </Field>
              <Field label="Maximum due sources">
                <input
                  min="1"
                  max="500"
                  type="number"
                  value={socialLimit}
                  onChange={(event) => setSocialLimit(event.target.value)}
                />
              </Field>
            </div>
            <SocialHealth
              status={socialStatus}
              loading={statusLoading}
              error={statusError}
              refresh={loadSocialStatus}
            />
          </>
        )}
        <button className="primary" disabled={busy} onClick={submit}>
          <Play size={15} />
          {busy
            ? "Queueing..."
            : selected === "INGEST_SOCIAL_FEEDS"
              ? "Run due social feeds"
              : "Queue operation"}
        </button>
      </section>
    </div>
  );
}

function SocialHealth({
  status,
  loading,
  error,
  refresh,
}: {
  status: SocialIngestionSummary | null;
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="socialHealth" aria-live="polite">
      <div className="socialHealthHeader">
        <div>
          <h3>Pipeline health</h3>
          <p>
            Only due subscriptions are polled. New documents are enriched and
            classified in the same run.
          </p>
        </div>
        <button
          className="iconButton"
          aria-label="Refresh social ingestion status"
          disabled={loading}
          onClick={() => void refresh()}
        >
          <RefreshCw className={loading ? "spinning" : ""} size={14} />
        </button>
      </div>
      {error && <p className="socialStatusError">{error}</p>}
      {!status && !error && (
        <p className="socialStatusLoading">Loading pipeline status…</p>
      )}
      {status && (
        <>
          <dl className="socialMetrics">
            <div><dt>Subscriptions</dt><dd>{formatNumber(status.enabled_subscriptions)}</dd></div>
            <div><dt>Due now</dt><dd>{formatNumber(status.due_subscriptions)}</dd></div>
            <div><dt>Documents</dt><dd>{formatNumber(status.documents)}</dd></div>
            <div><dt>Unresolved</dt><dd>{formatNumber(status.unresolved)}</dd></div>
          </dl>
          <div className="socialProviderTable">
            <table>
              <thead><tr><th>Provider</th><th className="num">Subscriptions</th><th className="num">Due</th></tr></thead>
              <tbody>
                {Object.entries(status.providers).map(([provider, values]) => (
                  <tr key={provider}>
                    <td><strong>{label(provider)}</strong></td>
                    <td className="num">{formatNumber(values.subscriptions)}</td>
                    <td className="num">{formatNumber(values.due)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="socialHealthFoot">
            <span>Latest poll <strong>{time(status.latest_success_at)}</strong></span>
            <span>Enrichment pending <strong>{formatNumber(status.enrichments.PENDING ?? 0)}</strong></span>
            <span>Positive / negative <strong>{formatNumber(status.sentiments.POSITIVE ?? 0)} / {formatNumber(status.sentiments.NEGATIVE ?? 0)}</strong></span>
          </div>
        </>
      )}
    </section>
  );
}
