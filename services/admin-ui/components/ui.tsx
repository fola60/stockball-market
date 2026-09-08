import type React from "react";
import { X } from "lucide-react";

export function DetailPanel({
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
export function DetailList({ items }: { items: Array<[string, string | number]> }) {
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
export function JsonSection({
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

export function Field({
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
export function Stat({
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
export function Status({ value }: { value: string }) {
  return <span className={`status s-${value.toLowerCase()}`}>{value}</span>;
}

