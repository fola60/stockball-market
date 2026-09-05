"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRightLeft,
  Bot,
  ChevronLeft,
  ChevronRight,
  Database,
  Pause,
  Play,
  RefreshCw,
  Timer,
  X,
} from "lucide-react";

const API =
  process.env.NEXT_PUBLIC_STOCKBALL_API_URL ?? "http://localhost:8000";
type View = "runs" | "processes" | "ingestion" | "traders" | "trades";
type Run = {
  id: string;
  operation_type: string;
  job_type: string;
  status: string;
  attempt: number;
  successful_items: number;
  skipped_items: number;
  failed_items: number;
  retryable_failures: number;
  metrics: Record<string, unknown>;
  parameters: Record<string, unknown>;
  error_message?: string;
  enqueued_at: string;
  started_at?: string;
  completed_at?: string;
};
type Summary = {
  total_24h: number;
  succeeded_24h: number;
  failed_24h: number;
  successful_items_24h: number;
  failed_items_24h: number;
  bot_statuses: Record<string, number>;
};
type Trader = {
  id: string;
  bot_key: string;
  display_name: string;
  status: string;
  strategy_engine: string;
  config_key: string;
  cash_balance: string;
  position_count: number;
  last_ticked_at?: string;
};
type Profile = {
  config_key: string;
  display_name: string;
  strategy_engine: string;
  enabled: boolean;
};
type Position = {
  instrument_id: string;
  symbol: string;
  display_name: string;
  club?: string;
  quantity: string;
  current_price: string;
  market_value: string;
  last_trade_price?: string;
  last_trade_at?: string;
  updated_at: string;
};
type Trade = {
  id: string;
  symbol: string;
  side: string;
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
};
type BotDetail = Trader & {
  account_id: string;
  portfolio_id: string;
  handle: string;
  profile_name: string;
  config_version: number;
  config: Record<string, unknown>;
  config_overrides: Record<string, unknown>;
  next_tick_after?: string;
  position_value: string;
  total_equity: string;
  positions: Position[];
  recent_trades: Trade[];
  activity: {
    trades_today: number;
    turnover_today: string;
    last_trade_at?: string;
  };
};
type LedgerTrade = {
  id: string;
  order_id: string;
  account_id: string;
  portfolio_id: string;
  instrument_id: string;
  side: string;
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
  symbol: string;
  instrument_name: string;
  player_name?: string;
  club?: string;
  handle: string;
  account_name: string;
  account_type: string;
  actor_name: string;
  bot_id?: string;
  bot_key?: string;
  bot_name?: string;
  strategy_engine?: string;
};
type TradeSummary = {
  total: number;
  buys: number;
  sells: number;
  user_trades: number;
  synthetic_trades: number;
  gross_amount: string;
};
type TradePage = {
  items: LedgerTrade[];
  total: number;
  limit: number;
  offset: number;
  summary: TradeSummary;
};
type TradeDetail = LedgerTrade & {
  created_at: string;
  request_id: string;
  order_status: string;
  submitted_at: string;
  filled_at?: string;
  rejection_reason?: string;
  email?: string;
  account_status: string;
  current_cash_balance: string;
  current_position_quantity?: string;
  instrument_type: string;
  current_price: string;
  trading_status: string;
  player_id?: string;
  player_position?: string;
  bot_status?: string;
  last_ticked_at?: string;
  next_tick_after?: string;
  config_key?: string;
  profile_name?: string;
  config_version?: number;
  old_price?: string;
  new_price?: string;
  price_change_reason?: string;
  cash_ledger_reason?: string;
  cash_amount_delta?: string;
  cash_balance_after?: string;
};
type ProcessJob = {
  job_type: string;
  payload: Record<string, unknown>;
  attempt: number;
  operation_run_id?: string;
  started_at?: string;
};
type RecurringProcess = {
  name: string;
  display_name: string;
  job_type: string;
  schedule: string;
  enabled: boolean;
  default_enabled: boolean;
  running: boolean;
  queued: number;
};
type ProcessSnapshot = {
  scheduler: {
    online: boolean;
    last_seen_at?: string;
    last_scheduled: string[];
  };
  active_job?: ProcessJob;
  queued_jobs: ProcessJob[];
  processes: RecurringProcess[];
};

const EMPTY_SUMMARY: Summary = {
  total_24h: 0,
  succeeded_24h: 0,
  failed_24h: 0,
  successful_items_24h: 0,
  failed_items_24h: 0,
  bot_statuses: {},
};
const EMPTY_PROCESSES: ProcessSnapshot = {
  scheduler: { online: false, last_scheduled: [] },
  queued_jobs: [],
  processes: [],
};
const INGEST_COMMANDS = [
  ["INGEST_PLAYERS", "Players", "Fetch and upsert league players"],
  ["INGEST_FIXTURES", "Fixtures", "Fetch fixtures for a league and season"],
  ["INGEST_PLAYER_STATS", "Player stats", "Fetch current player statistics"],
  ["IMPORT_MARKET_VALUES", "Market values", "Import Transfermarkt CSV files"],
  [
    "SEED_PLAYER_SHARES",
    "Player shares",
    "Create missing player-share instruments",
  ],
  [
    "INGEST_BETTING_MARKETS",
    "Betting markets",
    "Ingest Bet365 market observations",
  ],
  [
    "INGEST_TWITTER_INJURIES",
    "Injury reports",
    "Ingest configured injury-report query",
  ],
] as const;

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok)
    throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

export default function Home() {
  const [view, setView] = useState<View>("runs");
  const [runs, setRuns] = useState<Run[]>([]);
  const [summary, setSummary] = useState<Summary>(EMPTY_SUMMARY);
  const [traders, setTraders] = useState<Trader[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [processes, setProcesses] = useState<ProcessSnapshot>(EMPTY_PROCESSES);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextRuns, nextSummary, nextTraders, nextProfiles, nextProcesses] =
        await Promise.all([
          getJson<Run[]>("/internal/v1/dev/runs?limit=100"),
          getJson<Summary>("/internal/v1/dev/summary"),
          getJson<Trader[]>("/internal/v1/dev/synthetic-traders"),
          getJson<Profile[]>("/internal/v1/dev/synthetic-trader-profiles"),
          getJson<ProcessSnapshot>("/internal/v1/dev/processes"),
        ]);
      setRuns(nextRuns);
      setSummary(nextSummary);
      setTraders(nextTraders);
      setProfiles(nextProfiles);
      setProcesses(nextProcesses);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "API unavailable");
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 5000);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [refresh]);

  async function enqueue(
    operation_type: string,
    parameters: Record<string, unknown> = {},
  ) {
    setBusy(true);
    try {
      const response = await fetch(`${API}/internal/v1/dev/operations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_type, parameters }),
      });
      if (!response.ok) throw new Error(await response.text());
      setView("runs");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }

  async function setProcessEnabled(name: string, enabled: boolean) {
    setBusy(true);
    try {
      const response = await fetch(
        `${API}/internal/v1/dev/processes/${name}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        },
      );
      if (!response.ok) throw new Error(await response.text());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Process update failed");
    } finally {
      setBusy(false);
    }
  }

  const completed = summary.succeeded_24h + summary.failed_24h;
  const successRate = completed
    ? Math.round((summary.succeeded_24h / completed) * 100)
    : 0;
  const activeBots = summary.bot_statuses.ACTIVE ?? 0;

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span>SB</span>
          <div>
            <strong>Stockball</strong>
            <small>DEV PORTAL</small>
          </div>
        </div>
        <nav>
          <Nav
            active={view === "runs"}
            icon={<Activity />}
            label="Runs"
            onClick={() => setView("runs")}
          />
          <Nav
            active={view === "processes"}
            icon={<Timer />}
            label="Processes"
            onClick={() => setView("processes")}
          />
          <Nav
            active={view === "ingestion"}
            icon={<Database />}
            label="Ingestion"
            onClick={() => setView("ingestion")}
          />
          <Nav
            active={view === "traders"}
            icon={<Bot />}
            label="Synthetic traders"
            onClick={() => setView("traders")}
          />
          <Nav
            active={view === "trades"}
            icon={<ArrowRightLeft />}
            label="Trades"
            onClick={() => setView("trades")}
          />
        </nav>
        <div className="environment">
          <i /> LOCAL / DEV
        </div>
      </aside>
      <section className="workspace">
        <header>
          <div>
            <h1>
              {view === "runs"
                ? "Operation runs"
                : view === "processes"
                  ? "Recurring processes"
                : view === "ingestion"
                  ? "Data ingestion"
                  : view === "traders"
                    ? "Synthetic traders"
                    : "Trades"}
            </h1>
            <p>
              {view === "runs"
                ? "Worker execution history and batch outcomes"
                : view === "processes"
                  ? "Schedules, queue state, and active worker execution"
                : view === "ingestion"
                  ? "Run typed data import and seeding commands"
                  : view === "traders"
                    ? "Manage bot fleet, ticks, funding, and portfolios"
                    : "Executed orders across users and synthetic traders"}
            </p>
          </div>
          <button className="iconButton" title="Refresh data" onClick={refresh}>
            <RefreshCw size={16} />
          </button>
        </header>
        {error && (
          <div className="error">
            <strong>API error</strong>
            <span>{error}</span>
          </div>
        )}
        {view === "runs" && (
          <RunsView
            runs={runs}
            summary={summary}
            rate={successRate}
            enqueue={enqueue}
          />
        )}
        {view === "processes" && (
          <ProcessesView
            snapshot={processes}
            busy={busy}
            setEnabled={setProcessEnabled}
          />
        )}
        {view === "ingestion" && (
          <IngestionView enqueue={enqueue} busy={busy} />
        )}
        {view === "traders" && (
          <TradersView
            traders={traders}
            profiles={profiles}
            activeBots={activeBots}
            enqueue={enqueue}
            busy={busy}
          />
        )}
        {view === "trades" && <TradesView />}
      </section>
    </main>
  );
}

function Nav({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={active ? "nav active" : "nav"} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function ProcessesView({
  snapshot,
  busy,
  setEnabled,
}: {
  snapshot: ProcessSnapshot;
  busy: boolean;
  setEnabled: (name: string, enabled: boolean) => void;
}) {
  const enabled = snapshot.processes.filter((process) => process.enabled).length;
  return (
    <>
      <div className="stats">
        <Stat
          label="Scheduler"
          value={snapshot.scheduler.online ? "Online" : "Offline"}
          bad={!snapshot.scheduler.online}
        />
        <Stat label="Enabled schedules" value={enabled} />
        <Stat label="Queued jobs" value={snapshot.queued_jobs.length} />
        <Stat label="Worker" value={snapshot.active_job ? "Running" : "Idle"} />
      </div>
      <section className="activeProcess">
        <h2>Currently running</h2>
        {snapshot.active_job ? (
          <div className="activeJobRow">
            <div>
              <strong>{label(snapshot.active_job.job_type)}</strong>
              <small>
                Started {time(snapshot.active_job.started_at)} · attempt {snapshot.active_job.attempt}
              </small>
            </div>
            <Status value="RUNNING" />
          </div>
        ) : (
          <div className="idleState">No worker job is currently running.</div>
        )}
      </section>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Process</th>
              <th>Schedule</th>
              <th>Status</th>
              <th className="num">Queued</th>
              <th>Default</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {snapshot.processes.map((process) => (
              <tr key={process.name}>
                <td>
                  <strong>{process.display_name}</strong>
                  <small>{process.job_type}</small>
                </td>
                <td>{process.schedule}</td>
                <td>
                  <Status
                    value={
                      process.running
                        ? "RUNNING"
                        : process.enabled
                          ? "ACTIVE"
                          : "PAUSED"
                    }
                  />
                </td>
                <td className="num">{process.queued}</td>
                <td>{process.default_enabled ? "Enabled" : "Paused"}</td>
                <td className="processAction">
                  <button
                    className={process.enabled ? "" : "primary"}
                    disabled={busy}
                    onClick={() => setEnabled(process.name, !process.enabled)}
                  >
                    {process.enabled ? <Pause size={14} /> : <Play size={14} />}
                    {process.enabled ? "Pause" : "Start"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="processFooter">
        Scheduler heartbeat: {time(snapshot.scheduler.last_seen_at)}
      </div>
    </>
  );
}

function RunsView({
  runs,
  summary,
  rate,
  enqueue,
}: {
  runs: Run[];
  summary: Summary;
  rate: number;
  enqueue: (a: string, b?: Record<string, unknown>) => void;
}) {
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  return (
    <>
      <div className="stats">
        <Stat label="Runs (24h)" value={summary.total_24h} />
        <Stat label="Success rate" value={`${rate}%`} />
        <Stat label="Successful items" value={summary.successful_items_24h} />
        <Stat
          label="Failed items"
          value={summary.failed_items_24h}
          bad={summary.failed_items_24h > 0}
        />
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Operation</th>
              <th>Status</th>
              <th>Queued</th>
              <th>Duration</th>
              <th className="num">Success</th>
              <th className="num">Skipped</th>
              <th className="num">Failed</th>
              <th>Details</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.id}
                className="clickableRow"
                onClick={() => setSelectedRun(run)}
              >
                <td>
                  <button
                    className="textButton"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedRun(run);
                    }}
                  >
                    <strong>{label(run.operation_type)}</strong>
                    <small>{run.id.slice(0, 8)}</small>
                  </button>
                </td>
                <td>
                  <Status value={run.status} />
                </td>
                <td>{time(run.enqueued_at)}</td>
                <td>{duration(run)}</td>
                <td className="num good">{run.successful_items}</td>
                <td className="num">{run.skipped_items}</td>
                <td className="num badText">{run.failed_items}</td>
                <td className="details">
                  {run.error_message ?? metricText(run)}
                </td>
                <td>
                  <button
                    className="iconButton"
                    title="Queue this operation again"
                    onClick={(event) => {
                      event.stopPropagation();
                      enqueue(run.operation_type, run.parameters);
                    }}
                  >
                    <RefreshCw size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {!runs.length && (
              <tr>
                <td colSpan={9} className="empty">
                  No operation runs recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {selectedRun && (
        <RunDetails
          run={selectedRun}
          close={() => setSelectedRun(null)}
          enqueue={enqueue}
        />
      )}
    </>
  );
}

const EMPTY_TRADE_PAGE: TradePage = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0,
  summary: {
    total: 0,
    buys: 0,
    sells: 0,
    user_trades: 0,
    synthetic_trades: 0,
    gross_amount: "0",
  },
};

function TradesView() {
  const [data, setData] = useState<TradePage>(EMPTY_TRADE_PAGE),
    [offset, setOffset] = useState(0);
  const [accountType, setAccountType] = useState("ALL"),
    [side, setSide] = useState("ALL");
  const [selectedTrade, setSelectedTrade] = useState<TradeDetail | null>(null),
    [error, setError] = useState("");
  const limit = 50;
  const load = useCallback(async () => {
    try {
      const query = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (accountType !== "ALL") query.set("account_type", accountType);
      if (side !== "ALL") query.set("side", side);
      setData(await getJson<TradePage>(`/internal/v1/dev/trades?${query}`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load trades");
    }
  }, [offset, accountType, side]);
  useEffect(() => {
    const initial = setTimeout(load, 0);
    const timer = setInterval(load, 5000);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [load]);
  async function openTrade(tradeId: string) {
    setError("");
    try {
      setSelectedTrade(
        await getJson<TradeDetail>(`/internal/v1/dev/trades/${tradeId}`),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load trade");
    }
  }
  function filterAccount(value: string) {
    setAccountType(value);
    setOffset(0);
  }
  function filterSide(value: string) {
    setSide(value);
    setOffset(0);
  }
  const page = Math.floor(offset / limit) + 1,
    pages = Math.max(1, Math.ceil(data.total / limit));
  return (
    <>
      {error && (
        <div className="error">
          <strong>Trade error</strong>
          <span>{error}</span>
        </div>
      )}
      <div className="stats tradeStats">
        <Stat label="Trades" value={data.summary.total} />
        <Stat label="Buys" value={data.summary.buys} />
        <Stat label="Sells" value={data.summary.sells} />
        <Stat label="Gross volume" value={money(data.summary.gross_amount)} />
      </div>
      <div className="tradeToolbar">
        <div>
          <label>
            Actor
            <select
              value={accountType}
              onChange={(event) => filterAccount(event.target.value)}
            >
              <option value="ALL">All actors</option>
              <option value="USER">Users</option>
              <option value="SYNTHETIC_TRADER">Synthetic traders</option>
              <option value="ADMIN">Admins</option>
            </select>
          </label>
          <label>
            Side
            <select
              value={side}
              onChange={(event) => filterSide(event.target.value)}
            >
              <option value="ALL">All sides</option>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
            </select>
          </label>
        </div>
        <button className="iconButton" title="Refresh trades" onClick={load}>
          <RefreshCw size={15} />
        </button>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Executed</th>
              <th>Actor</th>
              <th>Type</th>
              <th>Instrument</th>
              <th>Side</th>
              <th className="num">Shares</th>
              <th className="num">Price</th>
              <th className="num">Gross</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((trade) => (
              <tr
                key={trade.id}
                className="clickableRow"
                onClick={() => openTrade(trade.id)}
              >
                <td>{time(trade.executed_at)}</td>
                <td>
                  <button
                    className="textButton"
                    onClick={(event) => {
                      event.stopPropagation();
                      openTrade(trade.id);
                    }}
                  >
                    <strong>{trade.actor_name}</strong>
                    <small>{trade.bot_key ?? trade.handle}</small>
                  </button>
                </td>
                <td>{label(trade.account_type)}</td>
                <td>
                  <strong>{trade.symbol}</strong>
                  <small>{trade.club ?? trade.instrument_name}</small>
                </td>
                <td>
                  <Status value={trade.side} />
                </td>
                <td className="num">{formatNumber(trade.shares)}</td>
                <td className="num">{money(trade.execution_price)}</td>
                <td className="num">{money(trade.gross_amount)}</td>
              </tr>
            ))}
            {!data.items.length && (
              <tr>
                <td colSpan={8} className="empty">
                  No trades recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <span>
          Page {page} of {pages} · {data.total.toLocaleString()} trades
        </span>
        <div>
          <button
            className="iconButton"
            title="Previous page"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            className="iconButton"
            title="Next page"
            disabled={offset + limit >= data.total}
            onClick={() => setOffset(offset + limit)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      {selectedTrade && (
        <TradeDetails
          trade={selectedTrade}
          close={() => setSelectedTrade(null)}
        />
      )}
    </>
  );
}

function TradeDetails({
  trade,
  close,
}: {
  trade: TradeDetail;
  close: () => void;
}) {
  return (
    <DetailPanel
      title={`${trade.side} ${trade.symbol}`}
      subtitle={trade.id}
      close={close}
    >
      <div className="detailStats">
        <Stat label="Shares" value={formatNumber(trade.shares)} />
        <Stat label="Execution price" value={money(trade.execution_price)} />
        <Stat label="Gross amount" value={money(trade.gross_amount)} />
      </div>
      <DetailList
        items={[
          ["Executed", time(trade.executed_at)],
          ["Actor", trade.actor_name],
          ["Account type", label(trade.account_type)],
          ["Handle", trade.handle],
          ["Account ID", trade.account_id],
          ["Portfolio ID", trade.portfolio_id],
        ]}
      />
      <section className="detailSection">
        <h3>Order</h3>
        <DetailList
          items={[
            ["Order ID", trade.order_id],
            ["Request ID", trade.request_id],
            ["Status", trade.order_status],
            ["Submitted", time(trade.submitted_at)],
            ["Filled", time(trade.filled_at)],
            ["Rejection", trade.rejection_reason ?? "-"],
          ]}
        />
      </section>
      <section className="detailSection">
        <h3>Instrument and settlement</h3>
        <DetailList
          items={[
            ["Instrument", `${trade.symbol} · ${trade.instrument_name}`],
            ["Player", trade.player_name ?? "-"],
            ["Club", trade.club ?? "-"],
            ["Position", trade.player_position ?? "-"],
            ["Price move", priceMove(trade.old_price, trade.new_price)],
            ["Current price", money(trade.current_price)],
            ["Cash movement", signedMoney(trade.cash_amount_delta)],
            [
              "Cash after trade",
              money(trade.cash_balance_after ?? trade.current_cash_balance),
            ],
            ["Current cash", money(trade.current_cash_balance)],
            [
              "Current holding",
              formatNumber(trade.current_position_quantity ?? 0),
            ],
          ]}
        />
      </section>
      {trade.bot_id && (
        <section className="detailSection">
          <h3>Synthetic trader</h3>
          <DetailList
            items={[
              ["Bot", trade.bot_name ?? "-"],
              ["Bot key", trade.bot_key ?? "-"],
              ["Status", trade.bot_status ?? "-"],
              ["Strategy", label(trade.strategy_engine ?? "")],
              ["Profile", trade.profile_name ?? "-"],
              ["Last tick", time(trade.last_ticked_at)],
              ["Next tick", time(trade.next_tick_after)],
              ["Bot ID", trade.bot_id],
            ]}
          />
        </section>
      )}
      {trade.account_type !== "SYNTHETIC_TRADER" && (
        <section className="detailSection">
          <h3>User account</h3>
          <DetailList
            items={[
              ["Display name", trade.account_name],
              ["Email", trade.email ?? "-"],
              ["Status", trade.account_status],
            ]}
          />
        </section>
      )}
    </DetailPanel>
  );
}

function IngestionView({
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

function TradersView({
  traders,
  profiles,
  activeBots,
  enqueue,
  busy,
}: {
  traders: Trader[];
  profiles: Profile[];
  activeBots: number;
  enqueue: (a: string, b?: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const [count, setCount] = useState("10"),
    [config, setConfig] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [seed, setSeed] = useState("42"),
    [dryRun, setDryRun] = useState(true);
  const [weeklyTopup, setWeeklyTopup] = useState("100000");
  const [tickCount, setTickCount] = useState("1");
  const [botDetail, setBotDetail] = useState<BotDetail | null>(null),
    [detailError, setDetailError] = useState("");
  const available = useMemo(
    () =>
      profiles.filter(
        (p) => p.enabled && p.strategy_engine !== "SOCIAL_SENTIMENT",
      ),
    [profiles],
  );
  const selectedConfig = config || available[0]?.config_key || "";
  function setStatus(status: string) {
    enqueue("SET_SYNTHETIC_TRADER_STATUS", { bot_ids: selected, status });
  }
  async function openBot(botId: string) {
    setDetailError("");
    try {
      setBotDetail(
        await getJson<BotDetail>(`/internal/v1/dev/synthetic-traders/${botId}`),
      );
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "Unable to load trader",
      );
    }
  }
  return (
    <>
      <div className="actions">
        <div>
          <strong>{traders.length}</strong>
          <span>Total bots</span>
        </div>
        <div>
          <strong>{activeBots}</strong>
          <span>Active</span>
        </div>
        <button
          onClick={() => enqueue("TICK_SYNTHETIC_TRADERS")}
          disabled={busy}
        >
          <Play size={15} /> Tick due bots
        </button>
        <label className="tickCount">
          <span>Ticks</span>
          <input
            type="number"
            min="1"
            max="100"
            step="1"
            value={tickCount}
            onChange={(event) => setTickCount(event.target.value)}
          />
        </label>
        <button
          onClick={() =>
            enqueue("TICK_SYNTHETIC_TRADERS", {
              force_timing: true,
              bot_ids: selected,
              tick_count: Number(tickCount),
            })
          }
          disabled={
            busy ||
            !Number.isInteger(Number(tickCount)) ||
            Number(tickCount) < 1 ||
            Number(tickCount) > 100
          }
        >
          <Play size={15} />{" "}
          {selected.length
            ? `Tick ${selected.length} now${Number(tickCount) > 1 ? ` ${tickCount} times` : ""}`
            : `Tick all now${Number(tickCount) > 1 ? ` ${tickCount} times` : ""}`}
        </button>
      </div>
      {detailError && (
        <div className="error">
          <strong>Detail error</strong>
          <span>{detailError}</span>
        </div>
      )}
      <div className="twoCol traderLayout">
        <section className="tableWrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Trader</th>
                <th>Status</th>
                <th>Strategy</th>
                <th>Last tick</th>
                <th className="num">Cash</th>
                <th className="num">Positions</th>
              </tr>
            </thead>
            <tbody>
              {traders.map((t) => (
                <tr
                  key={t.id}
                  className="clickableRow"
                  onClick={() => openBot(t.id)}
                >
                  <td onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.includes(t.id)}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...selected, t.id]
                            : selected.filter((id) => id !== t.id),
                        )
                      }
                    />
                  </td>
                  <td>
                    <button
                      className="textButton"
                      onClick={(event) => {
                        event.stopPropagation();
                        openBot(t.id);
                      }}
                    >
                      <strong>{t.display_name}</strong>
                      <small>{t.bot_key}</small>
                    </button>
                  </td>
                  <td>
                    <Status value={t.status} />
                  </td>
                  <td>{label(t.strategy_engine)}</td>
                  <td>{time(t.last_ticked_at)}</td>
                  <td className="num">
                    {Number(t.cash_balance).toLocaleString()}
                  </td>
                  <td className="num">{t.position_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <aside className="controls">
          <h2>Fleet commands</h2>
          <div className="buttonRow">
            <button
              disabled={!selected.length || busy}
              onClick={() => setStatus("ACTIVE")}
            >
              Resume
            </button>
            <button
              disabled={!selected.length || busy}
              onClick={() => setStatus("PAUSED")}
            >
              Pause
            </button>
            <button
              disabled={!selected.length || busy}
              onClick={() => setStatus("RETIRED")}
            >
              Retire
            </button>
          </div>
          <hr />
          <h3>Cash funding</h3>
          <Field label="Weekly amount per active trader">
            <input
              type="number"
              min="0.0001"
              step="1000"
              value={weeklyTopup}
              onChange={(e) => setWeeklyTopup(e.target.value)}
            />
          </Field>
          <button
            className="primary"
            disabled={busy || Number(weeklyTopup) <= 0}
            onClick={() =>
              enqueue("APPLY_TOPUPS", {
                cadence: "WEEKLY",
                synthetic_trader_amount: weeklyTopup,
              })
            }
          >
            Apply weekly top-up
          </button>
          <hr />
          <h3>Spawn traders</h3>
          <Field label="Profile">
            <select
              value={selectedConfig}
              onChange={(e) => setConfig(e.target.value)}
            >
              {available.map((p) => (
                <option key={p.config_key}>{p.config_key}</option>
              ))}
            </select>
          </Field>
          <Field label="Count">
            <input
              type="number"
              min="1"
              max="500"
              value={count}
              onChange={(e) => setCount(e.target.value)}
            />
          </Field>
          <button
            className="primary"
            disabled={busy || !selectedConfig}
            onClick={() =>
              enqueue("SPAWN_SYNTHETIC_TRADERS", {
                count: Number(count),
                config_key: selectedConfig,
              })
            }
          >
            Spawn
          </button>
          <hr />
          <h3>Bootstrap portfolios</h3>
          <Field label="Seed">
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />{" "}
            Dry run
          </label>
          <button
            className={dryRun ? "primary" : "dangerButton"}
            disabled={busy}
            onClick={() => {
              if (
                !dryRun &&
                !confirm(
                  "Commit portfolio allocations? Existing positions will not be replaced.",
                )
              )
                return;
              enqueue("BOOTSTRAP_SYNTHETIC_PORTFOLIOS", {
                all_active_synthetic_bots: true,
                seed: Number(seed),
                dry_run: dryRun,
              });
            }}
          >
            {dryRun ? "Run allocation preview" : "Commit allocation"}
          </button>
        </aside>
      </div>
      {botDetail && (
        <BotDetails bot={botDetail} close={() => setBotDetail(null)} />
      )}
    </>
  );
}

function RunDetails({
  run,
  close,
  enqueue,
}: {
  run: Run;
  close: () => void;
  enqueue: (a: string, b?: Record<string, unknown>) => void;
}) {
  return (
    <DetailPanel
      title={label(run.operation_type)}
      subtitle={run.id}
      close={close}
    >
      <div className="detailStats">
        <Stat label="Successful" value={run.successful_items} />
        <Stat label="Skipped" value={run.skipped_items} />
        <Stat
          label="Failed"
          value={run.failed_items}
          bad={run.failed_items > 0}
        />
      </div>
      <DetailList
        items={[
          ["Status", run.status],
          ["Job type", run.job_type],
          ["Attempt", run.attempt],
          ["Retryable failures", run.retryable_failures],
          ["Queued", time(run.enqueued_at)],
          ["Started", time(run.started_at)],
          ["Completed", time(run.completed_at)],
          ["Duration", duration(run)],
        ]}
      />
      {run.error_message && (
        <section className="detailSection">
          <h3>Error</h3>
          <pre className="errorBlock">{run.error_message}</pre>
        </section>
      )}
      {run.operation_type === "BOOTSTRAP_SYNTHETIC_PORTFOLIOS" && (
        <BootstrapSummary run={run} />
      )}{" "}
      {run.operation_type === "APPLY_TOPUPS" && <TopupSummary run={run} />}
      {run.operation_type === "TICK_SYNTHETIC_TRADERS" && (
        <TickSummary run={run} />
      )}
      <JsonSection title="Parameters" value={run.parameters} />
      <JsonSection title="Metrics" value={run.metrics} />
      <button
        className="primary"
        onClick={() => enqueue(run.operation_type, run.parameters)}
      >
        <RefreshCw size={14} /> Queue again
      </button>
    </DetailPanel>
  );
}

function BootstrapSummary({ run }: { run: Run }) {
  const metrics = run.metrics ?? {};
  const distribution = (metrics.distribution ?? {}) as Record<string, unknown>;
  const dryRun = Boolean(metrics.dry_run ?? run.parameters.dry_run);
  const projected = metricNumber(
    metrics.projected_positions,
    dryRun ? run.successful_items : 0,
  );
  return (
    <section className="detailSection">
      <h3>{dryRun ? "Allocation preview" : "Committed allocation"}</h3>
      <div className="summaryGrid">
        <SummaryItem
          label="Mode"
          value={dryRun ? "Preview only" : "Committed"}
        />
        <SummaryItem label="Bots" value={metricNumber(metrics.bots)} />
        <SummaryItem
          label="Total bot cash"
          value={money(String(metrics.total_bot_cash ?? 0))}
        />
        <SummaryItem
          label="Average bot cash"
          value={money(String(metrics.average_bot_cash ?? 0))}
        />
        <SummaryItem
          label="Instruments"
          value={metricNumber(metrics.instruments)}
        />
        <SummaryItem label="Projected positions" value={projected} />
        <SummaryItem
          label="Bot shares"
          value={formatNumber(metrics.bot_shares)}
        />
        <SummaryItem
          label="Reserve shares"
          value={formatNumber(metrics.reserve_shares)}
        />
        <SummaryItem
          label="Positions per bot"
          value={rangeText(
            distribution.min_positions_per_bot,
            distribution.max_positions_per_bot,
            distribution.avg_positions_per_bot,
          )}
        />
        <SummaryItem
          label="Shares per bot"
          value={rangeText(
            distribution.min_shares_per_bot,
            distribution.max_shares_per_bot,
            distribution.avg_shares_per_bot,
          )}
        />
      </div>
      {dryRun && (
        <p className="notice">
          No positions or allocation audit records were written.
        </p>
      )}
    </section>
  );
}
function TopupSummary({ run }: { run: Run }) {
  const metrics = run.metrics ?? {};
  return (
    <section className="detailSection">
      <h3>Cash funding</h3>
      <div className="summaryGrid">
        <SummaryItem
          label="Policies configured"
          value={metricNumber(metrics.configured_policies)}
        />
        <SummaryItem label="Accounts funded" value={run.successful_items} />
        <SummaryItem label="Already funded" value={run.skipped_items} />
        <SummaryItem
          label="Amount per trader"
          value={money(
            String(
              metrics.amount_per_synthetic_trader ??
                run.parameters.synthetic_trader_amount ??
                0,
            ),
          )}
        />
        <SummaryItem
          label="Total credited"
          value={money(String(metrics.credited_amount ?? 0))}
        />
        <SummaryItem label="Window" value={String(metrics.window ?? "-")} />
      </div>
    </section>
  );
}
function TickSummary({ run }: { run: Run }) {
  const metrics = run.metrics ?? {};
  const diagnostics = objectValue(metrics.decision_diagnostics);
  const decisions = objectValue(diagnostics.decisions);
  const profiles = objectValue(diagnostics.by_strategy);
  const tickDiagnostics = Array.isArray(metrics.tick_diagnostics)
    ? metrics.tick_diagnostics.map(objectValue)
    : [];
  const failedOrderSamples = Array.isArray(metrics.failed_order_samples)
    ? metrics.failed_order_samples.map(objectValue)
    : [];
  return (
    <>
      <section className="detailSection">
        <h3>Tick execution</h3>
        <div className="summaryGrid">
          <SummaryItem
            label="Ticks requested"
            value={metricNumber(metrics.ticks_requested, Number(run.parameters.tick_count ?? 1))}
          />
          <SummaryItem
            label="Ticks completed"
            value={metricNumber(metrics.ticks_completed)}
          />
          <SummaryItem label="Target" value={String(metrics.targeted_bots ?? "-")} />
          <SummaryItem label="Bots processed" value={metricNumber(metrics.processed_bots)} />
          <SummaryItem label="Trades executed" value={run.successful_items} />
          <SummaryItem label="Skipped outcomes" value={run.skipped_items} />
          <SummaryItem
            label="Candidates evaluated"
            value={metricNumber(diagnostics.candidates_evaluated)}
          />
          <SummaryItem
            label="Recovery candidates"
            value={metricNumber(diagnostics.recovery_decisions)}
          />
          <SummaryItem
            label="Recovery intents"
            value={metricNumber(diagnostics.recovery_orders)}
          />
          <SummaryItem label="Buy decisions" value={metricNumber(decisions.BUY)} />
          <SummaryItem label="Sell decisions" value={metricNumber(decisions.SELL)} />
          <SummaryItem label="Hold decisions" value={metricNumber(decisions.HOLD)} />
        </div>
      </section>
      {Object.keys(profiles).length > 0 && (
        <section className="detailSection">
          <h3>Decisions by strategy</h3>
          <div className="miniTable">
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Bots</th>
                  <th>Evaluated</th>
                  <th>Buy</th>
                  <th>Sell</th>
                  <th>Hold</th>
                  <th>Recovery intents / candidates</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(profiles).map(([strategy, raw]) => {
                  const profile = objectValue(raw);
                  const profileDecisions = objectValue(profile.decisions);
                  return (
                    <tr key={strategy}>
                      <td>{label(strategy)}</td>
                      <td>{metricNumber(profile.bots)}</td>
                      <td>{metricNumber(profile.candidates_evaluated)}</td>
                      <td>{metricNumber(profileDecisions.BUY)}</td>
                      <td>{metricNumber(profileDecisions.SELL)}</td>
                      <td>{metricNumber(profileDecisions.HOLD)}</td>
                      <td>
                        {metricNumber(profile.recovery_orders)} / {metricNumber(profile.recovery_decisions)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <DiagnosticCounts
        title="Candidate exclusions"
        values={objectValue(diagnostics.candidate_exclusions)}
      />
      <DiagnosticCounts
        title="Order rejection reasons"
        values={objectValue(diagnostics.rejection_reasons)}
      />
      <DiagnosticCounts
        title="Execution failure reasons"
        values={objectValue(metrics.execution_failures)}
      />
      <DiagnosticCounts
        title="Negative alpha"
        values={objectValue(diagnostics.negative_alpha)}
      />
      {tickDiagnostics.length > 1 && (
        <section className="detailSection">
          <h3>Iterations</h3>
          <div className="miniTable">
            <table>
              <thead>
                <tr>
                  <th>Tick</th>
                  <th>Bots</th>
                  <th>Evaluated</th>
                  <th>Recovery intents / candidates</th>
                </tr>
              </thead>
              <tbody>
                {tickDiagnostics.map((tick) => (
                  <tr key={String(tick.tick)}>
                    <td>{metricNumber(tick.tick)}</td>
                    <td>{metricNumber(tick.bots)}</td>
                    <td>{metricNumber(tick.candidates_evaluated)}</td>
                    <td>
                      {metricNumber(tick.recovery_orders)} / {metricNumber(tick.recovery_decisions)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {failedOrderSamples.length > 0 && (
        <section className="detailSection">
          <h3>Failed order samples</h3>
          <div className="miniTable">
            <table>
              <thead>
                <tr>
                  <th>Bot</th>
                  <th>Side</th>
                  <th>Instrument</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {failedOrderSamples.map((sample, index) => (
                  <tr key={`${String(sample.bot_id)}-${String(sample.instrument_id)}-${index}`}>
                    <td>{String(sample.bot_id ?? "-")}</td>
                    <td>{String(sample.side ?? "-")}</td>
                    <td>{String(sample.instrument_id ?? "-")}</td>
                    <td>{String(sample.message ?? sample.code ?? "Unknown error")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function DiagnosticCounts({
  title,
  values,
}: {
  title: string;
  values: Record<string, unknown>;
}) {
  const entries = Object.entries(values).filter(([, value]) => Number(value) > 0);
  if (entries.length === 0) return null;
  return (
    <section className="detailSection">
      <h3>{title}</h3>
      <div className="diagnosticCounts">
        {entries.map(([key, value]) => (
          <div key={key}>
            <span>{label(key)}</span>
            <strong>{formatNumber(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
function SummaryItem({
  label: caption,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div>
      <span>{caption}</span>
      <strong>{value}</strong>
    </div>
  );
}

function BotDetails({ bot, close }: { bot: BotDetail; close: () => void }) {
  return (
    <DetailPanel title={bot.display_name} subtitle={bot.bot_key} close={close}>
      <div className="detailStats">
        <Stat label="Cash" value={money(bot.cash_balance)} />
        <Stat label="Positions" value={bot.position_count} />
        <Stat label="Equity" value={money(bot.total_equity)} />
      </div>
      <DetailList
        items={[
          ["Status", bot.status],
          ["Strategy", label(bot.strategy_engine)],
          ["Profile", `${bot.profile_name} v${bot.config_version}`],
          ["Last tick", time(bot.last_ticked_at)],
          ["Next tick", time(bot.next_tick_after)],
          ["Trades today", bot.activity.trades_today],
          ["Turnover today", money(bot.activity.turnover_today)],
        ]}
      />
      <section className="detailSection">
        <h3>Positions</h3>
        <div className="miniTable">
          <table>
            <thead>
              <tr>
                <th>Instrument</th>
                <th className="num">Quantity</th>
                <th className="num">Price</th>
                <th className="num">Value</th>
                <th>Last trade</th>
              </tr>
            </thead>
            <tbody>
              {bot.positions.map((position) => (
                <tr key={position.instrument_id}>
                  <td>
                    <strong>{position.symbol}</strong>
                    <small>{position.club ?? position.display_name}</small>
                  </td>
                  <td className="num">
                    {Number(position.quantity).toLocaleString()}
                  </td>
                  <td className="num">{money(position.current_price)}</td>
                  <td className="num">{money(position.market_value)}</td>
                  <td>{time(position.last_trade_at)}</td>
                </tr>
              ))}
              {!bot.positions.length && (
                <tr>
                  <td colSpan={5} className="empty compact">
                    No open positions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <section className="detailSection">
        <h3>Recent trades</h3>
        <div className="miniTable">
          <table>
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Side</th>
                <th className="num">Shares</th>
                <th className="num">Execution</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {bot.recent_trades.map((trade) => (
                <tr key={trade.id}>
                  <td>{trade.symbol}</td>
                  <td>{trade.side}</td>
                  <td className="num">
                    {Number(trade.shares).toLocaleString()}
                  </td>
                  <td className="num">{money(trade.execution_price)}</td>
                  <td>{time(trade.executed_at)}</td>
                </tr>
              ))}
              {!bot.recent_trades.length && (
                <tr>
                  <td colSpan={5} className="empty compact">
                    No trades recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <JsonSection title="Config overrides" value={bot.config_overrides} />
    </DetailPanel>
  );
}

function DetailPanel({
  title,
  subtitle,
  close,
  children,
}: {
  title: string;
  subtitle: string;
  close: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="detailBackdrop" onClick={close}>
      <aside
        className="detailPanel"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h2>{title}</h2>
            <small>{subtitle}</small>
          </div>
          <button className="iconButton" title="Close details" onClick={close}>
            <X size={17} />
          </button>
        </header>
        {children}
      </aside>
    </div>
  );
}
function DetailList({ items }: { items: Array<[string, string | number]> }) {
  return (
    <dl className="detailList">
      {items.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function JsonSection({
  title,
  value,
}: {
  title: string;
  value: Record<string, unknown>;
}) {
  return (
    <section className="detailSection">
      <h3>{title}</h3>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function Field({
  label: caption,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{caption}</span>
      {children}
    </label>
  );
}
function Stat({
  label: caption,
  value,
  bad,
}: {
  label: string;
  value: string | number;
  bad?: boolean;
}) {
  return (
    <div className="stat">
      <span>{caption}</span>
      <strong className={bad ? "badText" : ""}>{value}</strong>
    </div>
  );
}
function Status({ value }: { value: string }) {
  return <span className={`status s-${value.toLowerCase()}`}>{value}</span>;
}
function label(value: string) {
  return value
    ? value
        .toLowerCase()
        .split("_")
        .map((v) => v[0].toUpperCase() + v.slice(1))
        .join(" ")
    : "-";
}
function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function time(value?: string) {
  return value ? new Date(value).toLocaleString() : "-";
}
function metricText(run: Run) {
  const metrics = run.metrics ?? {};
  if (metrics.dry_run)
    return `Preview: ${formatNumber(metrics.projected_positions ?? run.successful_items)} positions · ${formatNumber(metrics.bot_shares)} bot shares`;
  if (metrics.credited_amount !== undefined)
    return `${formatNumber(metrics.configured_policies)} policies · ${money(String(metrics.credited_amount))} credited`;
  const entries = Object.entries(metrics);
  return entries.length
    ? entries
        .slice(0, 2)
        .map(([k, v]) => `${label(k)}: ${v}`)
        .join(" · ")
    : "-";
}
function duration(run: Run) {
  if (typeof run.metrics?.elapsed_ms === "number")
    return `${run.metrics.elapsed_ms} ms`;
  if (run.completed_at)
    return `${Math.max(0, Math.round((new Date(run.completed_at).getTime() - new Date(run.enqueued_at).getTime()) / 1000))} s`;
  return "-";
}
function money(value: string) {
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
function signedMoney(value?: string) {
  if (value === undefined) return "-";
  const amount = Number(value);
  return `${amount > 0 ? "+" : ""}${money(value)}`;
}
function priceMove(oldPrice?: string, newPrice?: string) {
  return oldPrice === undefined || newPrice === undefined
    ? "-"
    : `${money(oldPrice)} → ${money(newPrice)}`;
}
function metricNumber(value: unknown, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
function formatNumber(value: unknown) {
  return metricNumber(value).toLocaleString();
}
function rangeText(minimum: unknown, maximum: unknown, average: unknown) {
  if (minimum === undefined || maximum === undefined) return "-";
  return `${formatNumber(minimum)}-${formatNumber(maximum)} (avg ${formatNumber(average)})`;
}
