"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRightLeft,
  Bot,
  Database,
  Gauge,
  RefreshCw,
  Settings2,
  Timer,
} from "lucide-react";

import { IngestionView } from "../features/ingestion/IngestionView";
import { ProcessesView } from "../features/processes/ProcessesView";
import { EnvironmentSettingsView } from "../features/settings/EnvironmentSettingsView";
import { TelemetryView } from "../features/telemetry/TelemetryView";
import { RunsView } from "../features/runs/RunsView";
import { TradersView } from "../features/traders/TradersView";
import { TradesView } from "../features/trades/TradesView";
import { getJson, patchJson, postJson } from "../lib/api";
import {
  DEFAULT_RUN_OPERATIONS,
  EMPTY_PROCESSES,
  EMPTY_SUMMARY,
  RUN_OPERATION_TYPES,
} from "../lib/constants";
import type {
  ProcessSnapshot,
  AuditEvent,
  EnvironmentVariable,
  OperationCapability,
  Profile,
  Run,
  Summary,
  TelemetrySnapshot,
  Trader,
  View,
} from "../lib/types";
import { usePolling } from "../lib/usePolling";

const VIEW_COPY: Record<View, [string, string]> = {
  runs: ["Operation runs", "Worker execution history and batch outcomes"],
  processes: ["Recurring processes", "Schedules, queue state, and active worker execution"],
  telemetry: ["Telemetry", "Trading activity, job health, and operational failures"],
  settings: ["Environment", "Edit every application variable with masked secrets and an audit trail"],
  ingestion: ["Data ingestion", "Run typed data import and seeding commands"],
  traders: ["Synthetic traders", "Manage bot fleet, ticks, funding, and portfolios"],
  trades: ["Trades", "Executed orders across users and synthetic traders"],
};

export default function Home() {
  const [view, setView] = useState<View>("runs");
  const [runs, setRuns] = useState<Run[]>([]);
  const [runOperations, setRunOperations] = useState<Set<string>>(
    () => new Set(DEFAULT_RUN_OPERATIONS),
  );
  const [operationTypes, setOperationTypes] = useState<string[]>([...RUN_OPERATION_TYPES]);
  const [summary, setSummary] = useState<Summary>(EMPTY_SUMMARY);
  const [traders, setTraders] = useState<Trader[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [processes, setProcesses] = useState<ProcessSnapshot>(EMPTY_PROCESSES);
  const [telemetry, setTelemetry] = useState<TelemetrySnapshot>();
  const [environment, setEnvironment] = useState<EnvironmentVariable[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getJson<OperationCapability[]>("/internal/v1/dev/operations/capabilities")
      .then((capabilities) => {
        const nextTypes = capabilities.map(({ operation_type }) => operation_type);
        setOperationTypes(nextTypes);
        setRunOperations(
          new Set(nextTypes.filter((type) => type !== "TICK_SYNTHETIC_TRADERS")),
        );
      })
      .catch(() => {
        // Keep the compiled fallback so the portal remains usable during API rollouts.
      });
  }, []);

  const refresh = useCallback(async () => {
    try {
      if (view === "runs") {
        const query = new URLSearchParams({ limit: "100" });
        operationTypes.filter((type) => !runOperations.has(type)).forEach((type) =>
          query.append("exclude_operation_type", type),
        );
        const [nextRuns, nextSummary] = await Promise.all([
          getJson<Run[]>(`/internal/v1/dev/runs?${query}`),
          getJson<Summary>("/internal/v1/dev/summary"),
        ]);
        setRuns(nextRuns);
        setSummary(nextSummary);
      } else if (view === "processes") {
        setProcesses(await getJson<ProcessSnapshot>("/internal/v1/dev/processes"));
      } else if (view === "telemetry") {
        setTelemetry(await getJson<TelemetrySnapshot>("/internal/v1/dev/telemetry?hours=24"));
      } else if (view === "settings") {
        const [nextSettings, nextAudit] = await Promise.all([
          getJson<EnvironmentVariable[]>("/internal/v1/dev/environment"),
          getJson<AuditEvent[]>("/internal/v1/dev/audit-events?limit=50"),
        ]);
        setEnvironment(nextSettings);
        setAuditEvents(nextAudit);
      } else if (view === "traders") {
        const [nextTraders, nextProfiles, nextSummary] = await Promise.all([
          getJson<Trader[]>("/internal/v1/dev/synthetic-traders"),
          getJson<Profile[]>("/internal/v1/dev/synthetic-trader-profiles"),
          getJson<Summary>("/internal/v1/dev/summary"),
        ]);
        setTraders(nextTraders);
        setProfiles(nextProfiles);
        setSummary(nextSummary);
      }
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "API unavailable");
    }
  }, [operationTypes, runOperations, view]);

  const manualRefresh = usePolling(refresh);

  async function enqueue(
    operationType: string,
    parameters: Record<string, unknown> = {},
  ) {
    setBusy(true);
    try {
      await postJson("/internal/v1/dev/operations", {
        operation_type: operationType,
        parameters,
      });
      setView("runs");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }

  async function setProcessEnabled(name: string, enabled: boolean) {
    setBusy(true);
    try {
      await patchJson(`/internal/v1/dev/processes/${name}`, { enabled });
      await manualRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Process update failed");
    } finally {
      setBusy(false);
    }
  }

  async function updateEnvironment(name: string, value: string, reason: string) {
    setBusy(true);
    try {
      await patchJson(`/internal/v1/dev/environment/${name}`, { value, reason });
      const [nextSettings, nextAudit] = await Promise.all([
        getJson<EnvironmentVariable[]>("/internal/v1/dev/environment"),
        getJson<AuditEvent[]>("/internal/v1/dev/audit-events?limit=50"),
      ]);
      setEnvironment(nextSettings);
      setAuditEvents(nextAudit);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Setting update failed");
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  const completed = summary.succeeded_24h + summary.failed_24h;
  const successRate = completed
    ? Math.round((summary.succeeded_24h / completed) * 100)
    : 0;
  const [title, description] = VIEW_COPY[view];

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span>SB</span>
          <div><strong>Stockball</strong><small>DEV PORTAL</small></div>
        </div>
        <nav>
          <Nav active={view === "runs"} icon={<Activity />} label="Runs" onClick={() => setView("runs")} />
          <Nav active={view === "processes"} icon={<Timer />} label="Processes" onClick={() => setView("processes")} />
          <Nav active={view === "telemetry"} icon={<Gauge />} label="Telemetry" onClick={() => setView("telemetry")} />
          <Nav active={view === "settings"} icon={<Settings2 />} label="Environment" onClick={() => setView("settings")} />
          <Nav active={view === "ingestion"} icon={<Database />} label="Ingestion" onClick={() => setView("ingestion")} />
          <Nav active={view === "traders"} icon={<Bot />} label="Synthetic traders" onClick={() => setView("traders")} />
          <Nav active={view === "trades"} icon={<ArrowRightLeft />} label="Trades" onClick={() => setView("trades")} />
        </nav>
        <div className="environment"><i /> LOCAL / DEV</div>
      </aside>
      <section className="workspace">
        <header>
          <div><h1>{title}</h1><p>{description}</p></div>
          {view !== "trades" && (
            <button className="iconButton" title="Refresh data" onClick={() => void manualRefresh()}>
              <RefreshCw size={16} />
            </button>
          )}
        </header>
        {error && <div className="error"><strong>API error</strong><span>{error}</span></div>}
        {view === "runs" && (
          <RunsView
            runs={runs}
            summary={summary}
            rate={successRate}
            enqueue={enqueue}
            selectedOperations={runOperations}
            setSelectedOperations={setRunOperations}
            operationTypes={operationTypes}
          />
        )}
        {view === "processes" && <ProcessesView snapshot={processes} busy={busy} setEnabled={setProcessEnabled} />}
        {view === "telemetry" && <TelemetryView snapshot={telemetry} />}
        {view === "settings" && <EnvironmentSettingsView variables={environment} audit={auditEvents} busy={busy} update={updateEnvironment} />}
        {view === "ingestion" && <IngestionView enqueue={enqueue} busy={busy} />}
        {view === "traders" && (
          <TradersView
            traders={traders}
            profiles={profiles}
            activeBots={summary.bot_statuses.ACTIVE ?? 0}
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
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={active ? "nav active" : "nav"} onClick={onClick}>
      {icon}<span>{label}</span>
    </button>
  );
}
