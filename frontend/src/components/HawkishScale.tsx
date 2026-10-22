import { t } from "../i18n";
import { fmtNum } from "../lib/format";

export function hawkishLabel(score: number | null | undefined): string {
  if (score === null || score === undefined) return t("tone.notScored");
  if (score <= -0.5) return t("tone.dovish");
  if (score <= -0.15) return t("tone.leanDovish");
  if (score < 0.15) return t("tone.neutral");
  if (score < 0.5) return t("tone.leanHawkish");
  return t("tone.hawkish");
}

/** A −1 (dovish) .. +1 (hawkish) scale with the score marked; text carries the value too. */
export function HawkishScale({ score, compact = false }: { score: number | null | undefined; compact?: boolean }) {
  const has = score !== null && score !== undefined && Number.isFinite(score);
  const clamped = has ? Math.max(-1, Math.min(1, score as number)) : 0;
  const pos = ((clamped + 1) / 2) * 100;
  const label = hawkishLabel(score);
  const signed = has ? `${(score as number) > 0 ? "+" : ""}${fmtNum(score as number, 2)}` : t("fmt.na");
  return (
    <div
      className={compact ? "hscale hscale-compact" : "hscale"}
      role="img"
      aria-label={has ? t("tone.aria", { score: signed, label: label.toLowerCase() }) : t("tone.notScoredYet")}
    >
      <div className="hscale-head">
        <span className="hscale-value num">{signed}</span>
        <span className="hscale-label">{label}</span>
      </div>
      <div className="hscale-track" aria-hidden="true">
        <span className="hscale-zero" />
        {has && (
          <>
            <span
              className={clamped < 0 ? "hscale-fill hscale-fill-dove" : "hscale-fill hscale-fill-hawk"}
              style={{ left: `${Math.min(pos, 50)}%`, width: `${Math.abs(pos - 50)}%` }}
            />
            <span className="hscale-dot" style={{ left: `${pos}%` }} />
          </>
        )}
      </div>
      {!compact && (
        <div className="hscale-ends" aria-hidden="true">
          <span>{t("tone.endDove")}</span>
          <span>0</span>
          <span>{t("tone.endHawk")}</span>
        </div>
      )}
    </div>
  );
}
