import { useCallback, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";

import { DetailList, DetailPanel, Stat, Status } from "../../components/ui";
import { getJson } from "../../lib/api";
import { formatNumber, label, money, priceMove, signedMoney, time } from "../../lib/format";
import type { TradeDetail, TradePage } from "../../lib/types";
import { usePolling } from "../../lib/usePolling";

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

export function TradesView() {
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
  usePolling(load);
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
