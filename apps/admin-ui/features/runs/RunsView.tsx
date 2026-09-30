import type React from "react";
import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { DetailList, DetailPanel, JsonSection, Stat, Status } from "../../components/ui";
import {
  duration,
  formatNumber,
  label,
  metricNumber,
  metricText,
  money,
  objectValue,
  rangeText,
  time,
} from "../../lib/format";
import type { Run, Summary } from "../../lib/types";

export function RunsView({
  runs,
  summary,
  rate,
  enqueue,
  selectedOperations,
  setSelectedOperations,
  operationTypes,
}: {
  runs: Run[];
  summary: Summary;
  rate: number;
  enqueue: (a: string, b?: Record<string, unknown>) => void;
  selectedOperations: Set<string>;
  setSelectedOperations: React.Dispatch<React.SetStateAction<Set<string>>>;
  operationTypes: string[];
}) {
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  function toggleOperation(operationType: string, checked: boolean) {
    setSelectedOperations((current) => {
      const next = new Set(current);
      if (checked) next.add(operationType);
      else next.delete(operationType);
      return next;
    });
  }
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
      <div className="runToolbar">
        <div className="runFilters">
          {operationTypes.map((operationType) => (
            <label className="runCheck" key={operationType}>
              <input
                type="checkbox"
                checked={selectedOperations.has(operationType)}
                onChange={(event) =>
                  toggleOperation(operationType, event.target.checked)
                }
              />
              {label(operationType)}
            </label>
          ))}
        </div>
        <span>
          Showing {runs.length} latest matching runs
        </span>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Operation</th>
              <th>Status</th>
              <th>Source</th>
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
                <td>
                  <strong>{label(run.source)}</strong>
                  <small>{run.schedule_name ?? "dev portal"}</small>
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
                <td colSpan={10} className="empty">
                  No runs match the selected filters.
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
          ["Source", label(run.source)],
          ["Schedule", run.schedule_name ?? "-"],
          ["Schedule window", run.schedule_window_key ?? "-"],
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
      {run.operation_type === "INGEST_SOCIAL_FEEDS" && (
        <SocialFeedSummary run={run} />
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

function SocialFeedSummary({ run }: { run: Run }) {
  const metrics = run.metrics ?? {};
  return (
    <section className="detailSection">
      <h3>Social ingestion</h3>
      <div className="summaryGrid">
        <SummaryItem label="Provider" value={String(metrics.provider ?? "ALL")} />
        <SummaryItem label="Sources polled" value={metricNumber(metrics.subscriptions_polled)} />
        <SummaryItem label="Entries fetched" value={metricNumber(metrics.fetched_documents)} />
        <SummaryItem label="New documents" value={metricNumber(metrics.inserted_documents)} />
        <SummaryItem label="Duplicates" value={metricNumber(metrics.duplicate_documents)} />
        <SummaryItem label="Articles enriched" value={metricNumber(metrics.articles_enriched)} />
        <SummaryItem label="Enrichment fallbacks" value={metricNumber(metrics.article_enrichments_skipped)} />
        <SummaryItem label="Documents classified" value={metricNumber(metrics.documents_processed)} />
        <SummaryItem label="Source failures" value={metricNumber(metrics.source_failures)} />
        <SummaryItem label="Processing failures" value={metricNumber(metrics.processing_failures)} />
      </div>
    </section>
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
