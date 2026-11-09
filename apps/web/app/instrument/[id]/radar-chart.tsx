"use client";

import { useState } from "react";
import { RadarHexagon } from "@/app/components/radar-hexagon";
import type { RadarAxis } from "@/lib/api";

function ordinal(value: number): string {
  const remainder = value % 100;
  if (remainder >= 11 && remainder <= 13) return `${value}th`;
  if (value % 10 === 1) return `${value}st`;
  if (value % 10 === 2) return `${value}nd`;
  if (value % 10 === 3) return `${value}rd`;
  return `${value}th`;
}

function MetricBreakdown({ axis, overlay = false }: { axis: RadarAxis; overlay?: boolean }) {
  return (
    <div className={`grid gap-px overflow-hidden rounded-lg border ${overlay ? "border-[#8fb5ff]/35 bg-[#8fb5ff]/15 shadow-[0_18px_35px_rgba(0,0,0,0.26)]" : "border-[#252e39] bg-[#252e39] sm:grid-cols-3"}`}>
      {axis.components.map((component) => (
        <div key={component.label} className={`px-3 py-3 ${overlay ? "bg-[#0b1016]/85" : "bg-[#0b1016]"}`}>
          <span className="block text-[11px] font-semibold leading-4 text-[#9aa4af]">{component.label}</span>
          <span className="mt-1.5 flex items-baseline justify-between gap-2 text-xs font-semibold text-white tabular-nums slashed-zero">
            {component.value}
            <small className="text-[11px] font-semibold text-[#8fb5ff]">{ordinal(component.score)}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

const tooltipPlacements = [
  { panel: "left-1/2 top-[14%] -translate-x-1/2", pointer: "-top-1.5 left-1/2 -translate-x-1/2 border-l border-t" },
  { panel: "right-[12%] top-[20%]", pointer: "-right-1.5 top-6 border-r border-t" },
  { panel: "right-[12%] top-[57%]", pointer: "-right-1.5 top-14 border-r border-t" },
  { panel: "bottom-[10%] left-1/2 -translate-x-1/2", pointer: "-bottom-1.5 left-1/2 -translate-x-1/2 border-b border-r" },
  { panel: "left-[12%] top-[57%]", pointer: "-left-1.5 top-14 border-b border-l" },
  { panel: "left-[12%] top-[20%]", pointer: "-left-1.5 top-6 border-b border-l" },
] as const;

function TraitTooltip({ axis, index }: { axis: RadarAxis; index: number }) {
  const placement = tooltipPlacements[index] ?? tooltipPlacements[0];

  return (
    <div aria-live="polite" className={`pointer-events-none absolute z-10 w-[280px] ${placement.panel}`}>
      <span aria-hidden className={`absolute z-0 h-3 w-3 rotate-45 border-[#8fb5ff]/35 bg-[#0b1016]/85 ${placement.pointer}`} />
      <div className="relative z-10 rounded-xl border border-[#8fb5ff]/35 bg-[#080b10]/55 p-2 backdrop-blur-[2px]">
        <strong className="mb-3 block px-1 text-sm font-semibold text-white">{axis.label}</strong>
        <MetricBreakdown axis={axis} overlay />
      </div>
    </div>
  );
}

export function RadarChart({ axes }: { axes: RadarAxis[] }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const activeAxis = activeIndex === null ? null : axes[activeIndex];

  return (
    <>
      <div className="divide-y divide-[#202630] sm:hidden">
        {axes.map((axis, index) => {
          const expanded = index === activeIndex;
          return (
            <div key={axis.label} className="py-1">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setActiveIndex(index)}
                className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-md px-1 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]"
              >
                <span className="text-xs font-semibold text-[#d9e0e8]">{axis.label}</span>
              <span className="text-right text-sm font-semibold text-[#8fb5ff] tabular-nums slashed-zero">{axis.score}</span>
              </button>
              {expanded ? <div className="pb-3"><MetricBreakdown axis={axis} /></div> : null}
            </div>
          );
        })}
      </div>

      <div className="hidden sm:block">
        <div className="relative mx-auto w-full max-w-[620px]">
        <RadarHexagon
          axes={axes}
          label={`Player composite profile: ${axes.map((axis) => `${axis.label} ${axis.score}`).join(", ")}`}
          activeIndex={activeIndex}
          onActiveChange={setActiveIndex}
          describeAxis={(index) => {
            const axis = axes[index];
            return `${axis.label}: ${axis.score} composite score. ${axis.components.map((component) => `${component.label}, ${component.value}, ${ordinal(component.score)} percentile`).join("; ")}`;
          }}
        />

        {activeAxis && activeIndex !== null ? (
          <TraitTooltip axis={activeAxis} index={activeIndex} />
        ) : null}
        </div>
      </div>
    </>
  );
}
