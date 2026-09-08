import { useState } from "react";
import { Play } from "lucide-react";

import { Field } from "../../components/ui";
import { INGEST_COMMANDS } from "../../lib/constants";

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
  const command = INGEST_COMMANDS.find((item) => item[0] === selected)!;
  function submit() {
    const base = { league: Number(league), season: Number(season) };
    let p: Record<string, unknown> = base;
    if (selected === "IMPORT_MARKET_VALUES")
      p = { valuations_csv: values, players_csv: players };
    if (selected === "INGEST_BETTING_MARKETS")
      p = { league: "Premier League", mode };
    if (selected === "INGEST_TWITTER_INJURIES") p = { query_key: queryKey };
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
            onClick={() => setSelected(item[0])}
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
        <button className="primary" disabled={busy} onClick={submit}>
          <Play size={15} />
          {busy ? "Queueing..." : "Queue operation"}
        </button>
      </section>
    </div>
  );
}


