import type { HorizonForecast } from "../api/types";

/** Nested 95/80/50 bars on a shared scale with a center tick and a spot reference. */
export function RangeBar({
  horizon,
  spot,
  domain,
}: {
  horizon: HorizonForecast;
  spot: number;
  domain: [number, number];
}) {
  const [d0, d1] = domain;
  const pct = (v: number) => ((v - d0) / (d1 - d0 || 1)) * 100;
  const bar = (k: "95" | "80" | "50") => {
    const b = horizon.bands[k];
    if (!b) return null;
    const left = pct(Math.min(b[0], b[1]));
    const right = pct(Math.max(b[0], b[1]));
    return <span className={`rbar-band rbar-${k}`} style={{ left: `${left}%`, width: `${right - left}%` }} />;
  };
  return (
    <div className="rbar" aria-hidden="true">
      {bar("95")}
      {bar("80")}
      {bar("50")}
      <span className="rbar-spot" style={{ left: `${pct(spot)}%` }} />
      <span className="rbar-center" style={{ left: `${pct(horizon.center)}%` }} />
    </div>
  );
}
