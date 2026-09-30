import { Stat, Status } from "../../components/ui";
import { money, time } from "../../lib/format";
import type { TelemetrySnapshot } from "../../lib/types";

export function TelemetryView({ snapshot }: { snapshot?: TelemetrySnapshot }) {
  if (!snapshot) return <div className="tableWrap"><div className="empty">Loading telemetry…</div></div>;
  const peak = Math.max(1, ...snapshot.activity.map((item) => item.trades + item.job_runs));
  const health = snapshot.service_health;
  return (
    <>
      <div className="stats">
        <Stat label="Executed trades" value={snapshot.overview.trades} />
        <Stat label="Gross volume" value={money(snapshot.overview.gross_volume)} />
        <Stat label="Order success" value={`${snapshot.overview.order_success_rate}%`} bad={snapshot.overview.order_success_rate < 95} />
        <Stat label="Failed jobs" value={snapshot.overview.failed_runs} bad={snapshot.overview.failed_runs > 0} />
      </div>
      <section className="telemetryHealth">
        <div><span>Scheduler</span><Status value={health?.scheduler.online ? "ONLINE" : "OFFLINE"} /></div>
        <div><span>Queue depth</span><strong>{health?.queue_depth ?? "—"}</strong></div>
        <div><span>Active worker job</span><strong>{health?.active_job?.job_type ?? "Idle"}</strong></div>
        <div><span>Frozen instruments</span><strong className={snapshot.overview.frozen_instruments ? "badText" : ""}>{snapshot.overview.frozen_instruments}</strong></div>
      </section>
      <div className="telemetryGrid">
        <section className="telemetryPanel activityPanel">
          <header><div><h2>Hourly activity</h2><p>Trades and worker runs over the last {snapshot.window_hours} hours</p></div><small>Updated {time(snapshot.generated_at)}</small></header>
          <div className="activityChart" aria-label="Hourly activity chart">
            {snapshot.activity.map((item) => (
              <div className="activityColumn" key={item.bucket} title={`${time(item.bucket)} · ${item.trades} trades · ${item.job_runs} jobs`}>
                <div className="activityBars">
                  <i style={{ height: `${Math.max(2, item.trades / peak * 100)}%` }} />
                  <b style={{ height: `${Math.max(2, item.job_runs / peak * 100)}%` }} />
                </div>
                <span>{new Date(item.bucket).getHours().toString().padStart(2, "0")}</span>
              </div>
            ))}
          </div>
          <div className="chartLegend"><span><i /> Trades</span><span><b /> Worker runs</span></div>
        </section>
        <section className="telemetryPanel">
          <header><div><h2>Order rejections</h2><p>Top reasons in this window</p></div></header>
          {snapshot.rejection_reasons.length ? (
            <div className="reasonList">{snapshot.rejection_reasons.map((item) => <div key={item.reason}><span>{item.reason}</span><strong>{item.count}</strong></div>)}</div>
          ) : <div className="quietEmpty">No rejected orders</div>}
        </section>
      </div>
      <section className="tableWrap telemetryOperations">
        <table><thead><tr><th>Operation</th><th>Latest success</th><th>Latest failure</th><th className="num">Failures</th></tr></thead>
          <tbody>{snapshot.operations.length ? snapshot.operations.map((item) => <tr key={item.operation_type}><td><strong>{item.operation_type.replaceAll("_", " ")}</strong></td><td>{item.latest_success_at ? time(item.latest_success_at) : "Never"}</td><td>{item.latest_failure_at ? time(item.latest_failure_at) : "Never"}</td><td className={item.failures ? "num badText" : "num"}>{item.failures}</td></tr>) : <tr><td colSpan={4} className="empty compact">No worker operations recorded</td></tr>}</tbody>
        </table>
      </section>
      <section className="endpointSection">
        <header><div><h2>Endpoint response times</h2><p>Latency percentiles and error rates for every API route in this process</p></div><span>{snapshot.endpoint_metrics.filter((item) => item.request_count).length} active / {snapshot.endpoint_metrics.length} routes</span></header>
        <div className="tableWrap endpointTable"><table><thead><tr><th>Endpoint</th><th className="num">Requests</th><th className="num">Errors</th><th className="num">Avg</th><th className="num">p50</th><th className="num">p90</th><th className="num">p95</th><th className="num">p99</th><th className="num">Max</th></tr></thead><tbody>
          {snapshot.endpoint_metrics.map((item) => <tr key={`${item.method}:${item.route}`}><td><span className={`method method-${item.method.toLowerCase()}`}>{item.method}</span><code>{item.route}</code></td><td className="num">{item.request_count.toLocaleString()}<small>{item.requests_per_minute}/min</small></td><td className={item.error_count ? "num badText" : "num"}>{item.error_count}<small>{item.error_rate}%</small></td><Latency value={item.average_ms} /><Latency value={item.p50_ms} /><Latency value={item.p90_ms} /><Latency value={item.p95_ms} /><Latency value={item.p99_ms} emphasize /><Latency value={item.max_ms} /></tr>)}
        </tbody></table></div>
      </section>
    </>
  );
}

function Latency({ value, emphasize = false }: { value?: number; emphasize?: boolean }) {
  return <td className={emphasize && value !== undefined && value > 500 ? "num badText latency" : "num latency"}>{value === undefined || value === null ? "—" : `${value.toLocaleString()} ms`}</td>;
}
