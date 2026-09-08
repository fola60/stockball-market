import { useMemo, useState } from "react";
import { Play } from "lucide-react";

import { DetailList, DetailPanel, Field, JsonSection, Stat, Status } from "../../components/ui";
import { getJson } from "../../lib/api";
import { label, money, time } from "../../lib/format";
import type { BotDetail, Profile, Trader } from "../../lib/types";

export function TradersView({
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


