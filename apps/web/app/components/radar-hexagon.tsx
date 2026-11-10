import type { KeyboardEvent } from "react";

/** `display` is printed under the label in place of the score when given, such as "7.5" or "High". */
export type RadarPoint = { label: string; score: number; display?: string };

const GEOMETRY = {
  // The player page's full-size profile.
  large: { width: 520, height: 440, cx: 260, cy: 220, radius: 142, labelRadius: 190, fontSize: 12 },
  // A tighter frame with larger type, for cards.
  compact: { width: 480, height: 350, cx: 240, cy: 178, radius: 110, labelRadius: 132, fontSize: 13 },
  // Narrow cards: a smaller frame keeps the type readable at phone widths.
  card: { width: 400, height: 300, cx: 200, cy: 152, radius: 90, labelRadius: 112, fontSize: 14 },
} as const;

function angleAt(index: number, count: number) {
  return -Math.PI / 2 + (index / count) * Math.PI * 2;
}

function polygonPoints(values: number[], radius: number, cx: number, cy: number): string {
  return values.map((value, index) => {
    const angle = angleAt(index, values.length);
    const scaled = radius * (value / 100);
    return `${cx + Math.cos(angle) * scaled},${cy + Math.sin(angle) * scaled}`;
  }).join(" ");
}

type Props = {
  axes: RadarPoint[];
  label: string;
  size?: keyof typeof GEOMETRY;
  accent?: string;
  /** Prints each axis score under its label. */
  showScores?: boolean;
  activeIndex?: number | null;
  /** Makes each axis focusable and reports hover, focus and clicks. */
  onActiveChange?: (index: number | null) => void;
  describeAxis?: (index: number) => string;
};

/** The hexagonal player profile: one axis per trait, each scored 0–100. */
export function RadarHexagon({ axes, label, size = "large", accent = "#8fb5ff", showScores = false, activeIndex = null, onActiveChange, describeAxis }: Props) {
  const { width, height, cx, cy, radius, labelRadius, fontSize } = GEOMETRY[size];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="h-auto w-full overflow-visible">
      {[20, 40, 60, 80, 100].map((level) => (
        <polygon key={level} points={polygonPoints(axes.map(() => level), radius, cx, cy)} fill={level === 100 ? "#0b1016" : "none"} stroke={level === 100 ? "#35404c" : "#252e39"} strokeWidth="1" vectorEffect="non-scaling-stroke" />
      ))}
      {axes.map((axis, index) => {
        const angle = angleAt(index, axes.length);
        return <line key={axis.label} x1={cx} y1={cy} x2={cx + Math.cos(angle) * radius} y2={cy + Math.sin(angle) * radius} stroke="#252e39" strokeWidth="1" vectorEffect="non-scaling-stroke" />;
      })}
      <polygon points={polygonPoints(axes.map((axis) => axis.score), radius, cx, cy)} fill={accent} fillOpacity="0.18" stroke={accent} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {axes.map((axis, index) => {
        const angle = angleAt(index, axes.length);
        const pointRadius = radius * (axis.score / 100);
        const labelX = cx + Math.cos(angle) * labelRadius;
        const labelY = cy + Math.sin(angle) * labelRadius;
        const textAnchor = Math.cos(angle) > 0.2 ? "start" : Math.cos(angle) < -0.2 ? "end" : "middle";
        const active = index === activeIndex;
        const interactive = onActiveChange ? {
          role: "button",
          tabIndex: 0,
          "aria-label": describeAxis?.(index) ?? `${axis.label}: ${axis.score}`,
          onMouseEnter: () => onActiveChange(index),
          onMouseLeave: () => onActiveChange(null),
          onFocus: () => onActiveChange(index),
          onBlur: () => onActiveChange(null),
          onClick: () => onActiveChange(index),
          onKeyDown: (event: KeyboardEvent) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onActiveChange(index);
            }
          },
          className: "cursor-pointer outline-none",
        } : {};
        return (
          <g key={axis.label} {...interactive}>
            <circle cx={cx + Math.cos(angle) * pointRadius} cy={cy + Math.sin(angle) * pointRadius} r={active ? "7" : "4"} fill={accent} stroke={active ? "#dce7ff" : "#080b10"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
            {onActiveChange && <circle cx={labelX} cy={labelY + 5} r="34" fill="transparent" />}
            <text x={labelX} y={labelY - (showScores ? 2 : 3)} textAnchor={textAnchor} fill={active ? "#ffffff" : "#d9e0e8"} fontSize={fontSize} fontWeight="650">
              {axis.label}
            </text>
            {showScores && (
              <text x={labelX} y={labelY + fontSize + 2} textAnchor={textAnchor} fill={accent} fontSize={fontSize} fontWeight="750" className="font-mono">
                {axis.display ?? axis.score}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
