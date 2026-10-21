import { scaleLinear } from "@visx/scale";
import type { BacktestMetricOut } from "../api/types";
import { BAND_NOMINAL, MODEL_LABELS, MODEL_ORDER } from "../lib/constants";
import { fmtPct } from "../lib/format";
import { useWidth } from "../lib/useWidth";

const ROWS = [
  { key: "cov50" as const, band: "50" as const },
  { key: "cov80" as const, band: "80" as const },
  { key: "cov95" as const, band: "95" as const },
];
const M = { top: 6, right: 16, bottom: 24, left: 44 };
const ROW_H = 34;

/** Dot plot: actual band coverage per model against the nominal level and its tolerance zone. */
export function CoverageChart({
  metrics,
  tolerance,
  title,
}: {
  metrics: BacktestMetricOut[];
  tolerance: number;
  title: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const models = [...metrics].sort((a, b) => MODEL_ORDER.indexOf(a.model) - MODEL_ORDER.indexOf(b.model));
  const height = M.top + ROWS.length * ROW_H + M.bottom;
  const innerW = Math.max(width - M.left - M.right, 10);
  const values = models.flatMap((m) => ROWS.map((r) => m[r.key]));
  const lo = Math.min(0.4, ...values.map((v) => v - 0.03));
  const x = scaleLinear<number>({ domain: [Math.floor(lo * 10) / 10, 1], range: [0, innerW] });
  const ticks = x.ticks(width < 420 ? 4 : 7);
  const offsets = models.length === 1 ? [0] : models.map((_, i) => (i - (models.length - 1) / 2) * 7);

  const summary = `${title}. ${ROWS.map(
    (r) =>
      `${r.band}% band: ${models.map((m) => `${MODEL_LABELS[m.model] ?? m.model} ${fmtPct(m[r.key])}`).join(", ")}`,
  ).join(". ")}.`;

  return (
    <div className="coverage" ref={ref}>
      <p className="coverage-title">Band coverage, actual against nominal</p>
      <ul className="legend legend-small" aria-label="Models">
        {models.map((m) => (
          <li key={m.model}>
            <span className={`legend-dot model-${m.model}`} />
            {MODEL_LABELS[m.model] ?? m.model}
          </li>
        ))}
        <li>
          <span className="legend-swatch coverage-zone-swatch" />
          Nominal &plusmn;{Math.round(tolerance * 100)} pts
        </li>
      </ul>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={summary} className="coverage-svg">
          <g transform={`translate(${M.left},${M.top})`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="coverage-grid" x1={x(t)} x2={x(t)} y1={0} y2={ROWS.length * ROW_H} />
                <text className="coverage-tick" x={x(t)} y={ROWS.length * ROW_H + 16} textAnchor="middle">
                  {Math.round(t * 100)}%
                </text>
              </g>
            ))}
            {ROWS.map((r, i) => {
              const nominal = BAND_NOMINAL[r.band];
              const cy = i * ROW_H + ROW_H / 2;
              return (
                <g key={r.key}>
                  <text className="coverage-row-label" x={-10} y={cy} dy="0.32em" textAnchor="end">
                    {r.band}%
                  </text>
                  <rect
                    className="coverage-zone"
                    x={x(nominal - tolerance)}
                    width={x(nominal + tolerance) - x(nominal - tolerance)}
                    y={cy - 12}
                    height={24}
                    rx={3}
                  />
                  <line className="coverage-nominal" x1={x(nominal)} x2={x(nominal)} y1={cy - 12} y2={cy + 12} />
                  {models.map((m, j) => (
                    <circle
                      key={m.model}
                      className={`coverage-dot model-${m.model}`}
                      cx={x(Math.min(1, Math.max(x.domain()[0], m[r.key])))}
                      cy={cy + offsets[j]}
                      r={4}
                    >
                      <title>{`${MODEL_LABELS[m.model] ?? m.model}: ${fmtPct(m[r.key])} inside the ${r.band}% band (nominal ${r.band}%)`}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </g>
        </svg>
      )}
    </div>
  );
}
