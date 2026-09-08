import { Pause, Play } from "lucide-react";

import { Stat, Status } from "../../components/ui";
import { label, time } from "../../lib/format";
import type { ProcessSnapshot } from "../../lib/types";

export function ProcessesView({
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

