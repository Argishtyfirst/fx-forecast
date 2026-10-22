import { t } from "../i18n";

/** Shown on every forecast (spec: Frontend rules; Risks: "Users read the center as a promise"). */
export function Disclaimer(_props: { text?: string | null }) {
  // The API's text is the same sentence in English; the translated one is shown.
  return (
    <p className="disclaimer" data-testid="disclaimer">
      {t("disclaimer")}
    </p>
  );
}
