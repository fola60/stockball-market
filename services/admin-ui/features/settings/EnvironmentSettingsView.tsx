import { useMemo, useState } from "react";
import { Eye, EyeOff, Save, Search } from "lucide-react";

import { time } from "../../lib/format";
import type { AuditEvent, EnvironmentVariable } from "../../lib/types";

export function EnvironmentSettingsView({ variables, audit, busy, update }: {
  variables: EnvironmentVariable[];
  audit: AuditEvent[];
  busy: boolean;
  update: (name: string, value: string, reason: string) => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Set<string>>(() => new Set());
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("ALL");
  const categories = useMemo(() => [...new Set(variables.map((item) => item.category))], [variables]);
  const filtered = variables.filter((item) => (category === "ALL" || item.category === category) && `${item.name} ${item.services.join(" ")}`.toLowerCase().includes(query.toLowerCase()));

  async function save(item: EnvironmentVariable, value: string) {
    await update(item.name, value, reason);
    setDrafts((current) => { const next = { ...current }; delete next[item.name]; return next; });
  }

  return <>
    <div className="settingsNotice"><strong>Project environment</strong><span>All values write to <code>.env</code>. Live scheduler values apply on the next poll; all others require service recreation.</span></div>
    <label className="changeReason"><span>Change reason</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required for the audit trail" /></label>
    <div className="environmentToolbar">
      <label><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search variables or services" /></label>
      <select value={category} onChange={(event) => setCategory(event.target.value)}><option value="ALL">All categories</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select>
      <span>{filtered.length} of {variables.length} variables</span>
    </div>
    <div className="tableWrap environmentTable"><table><thead><tr><th>Variable</th><th>Services</th><th>Value</th><th>Apply mode</th><th /></tr></thead><tbody>
      {filtered.map((item) => {
        const draft = drafts[item.name];
        const current = item.sensitive ? "" : (item.value ?? "");
        const value = draft ?? current;
        const changed = draft !== undefined && (item.sensitive ? draft.length > 0 : draft !== current);
        const show = revealed.has(item.name);
        return <tr key={item.name}><td><strong>{item.name}</strong><small>{item.category} · {item.value_type}{item.sensitive ? " · sensitive" : ""}</small></td><td><div className="serviceTags">{item.services.map((service) => <span key={service}>{service}</span>)}</div></td><td><div className="environmentValue"><input type={item.sensitive && !show ? "password" : "text"} value={value} placeholder={item.sensitive ? (item.has_value ? "Configured — enter replacement" : "Not configured") : "Empty"} onChange={(event) => setDrafts((currentDrafts) => ({ ...currentDrafts, [item.name]: event.target.value }))} />{item.sensitive && <button title={show ? "Hide typed value" : "Show typed value"} onClick={() => setRevealed((currentSet) => { const next = new Set(currentSet); if (show) next.delete(item.name); else next.add(item.name); return next; })}>{show ? <EyeOff size={14} /> : <Eye size={14} />}</button>}</div></td><td><span className={item.apply_mode === "next_scheduler_cycle" ? "applyMode live" : "applyMode restart"}>{item.apply_mode === "next_scheduler_cycle" ? "Next scheduler cycle" : "Recreate services"}</span></td><td className="environmentSave"><button disabled={busy || !changed || reason.trim().length < 3} onClick={() => void save(item, value).catch(() => undefined)}><Save size={14} /> Save</button></td></tr>;
      })}
    </tbody></table></div>
    <section className="tableWrap auditTable"><table><thead><tr><th>Time</th><th>Configuration</th><th>Change</th><th>Actor</th><th>Reason</th></tr></thead><tbody>
      {audit.length ? audit.map((item) => <tr key={item.id}><td>{time(item.created_at)}</td><td><strong>{item.target_key}</strong><small>{item.target_type.replaceAll("_", " ")}</small></td><td>{item.action.includes("RESET") ? "Reset to default" : `${String(item.before_value ?? "default")} → ${String(item.after_value ?? "empty")}`}</td><td>{item.actor}</td><td className="details" title={item.reason}>{item.reason}</td></tr>) : <tr><td className="empty compact" colSpan={5}>No configuration changes recorded</td></tr>}
    </tbody></table></section>
  </>;
}
