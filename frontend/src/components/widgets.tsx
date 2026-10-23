import type { ReactNode } from "react";

import { formatNumber } from "../lib/format";

export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{value}</span>;
}

export function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{typeof value === "number" ? formatNumber(value) : value}</dd>
      {hint && <small>{hint}</small>}
    </div>
  );
}

export function DbCard({
  title,
  engine,
  status,
  error,
  children,
}: {
  title: string;
  engine: string;
  status: "ok" | "error" | "unknown";
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <article className="card db-card">
      <header>
        <div>
          <h3>{title}</h3>
          <p className="muted">{engine}</p>
        </div>
        <span className={`dot dot-${status}`} role="img" aria-label={`status ${status}`} />
      </header>
      {status === "error" ? (
        <p role="alert" className="banner banner-error">
          Unavailable{error ? ` (${error})` : ""}
        </p>
      ) : (
        <dl className="stats">{children}</dl>
      )}
    </article>
  );
}

interface BarDatum {
  label: string;
  value: number;
}

/** Dependency-free SVG bar chart (accessible: summarised via aria-label, values in <title>). */
export function BarChart({ data, title, height = 160 }: { data: BarDatum[]; title: string; height?: number }) {
  if (data.length === 0) return <p className="muted">No data yet — run a migration, publish and process the queue.</p>;
  const width = Math.max(320, data.length * 22);
  const max = Math.max(...data.map((d) => d.value), 1);
  const gap = 6;
  const barWidth = (width - gap * (data.length + 1)) / data.length;
  const plotHeight = height - 22;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${title}: ${data.length} days, peak ${formatNumber(max)}`}
      className="bar-chart"
      preserveAspectRatio="none"
    >
      {data.map((d, i) => {
        const h = Math.max(2, (d.value / max) * (plotHeight - 4));
        const x = gap + i * (barWidth + gap);
        return (
          <g key={d.label}>
            <rect x={x} y={plotHeight - h} width={barWidth} height={h} rx={2}>
              <title>{`${d.label}: ${formatNumber(d.value)}`}</title>
            </rect>
            {(i % Math.ceil(data.length / 6) === 0 || i === data.length - 1) && (
              <text x={x + barWidth / 2} y={height - 6} textAnchor="middle">
                {d.label.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
