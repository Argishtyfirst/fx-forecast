import { t } from "../i18n";

/** NFR-08: credit every data source. */
export function Footer({ onResetTheme, manualTheme }: { onResetTheme: () => void; manualTheme: boolean }) {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-sources">
          <p className="footer-title">{t("footer.title")}</p>
          <ul>
            <li>
              <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html" target="_blank" rel="noreferrer">
                {t("footer.ecb")}
              </a>{" "}
              &middot; {t("footer.ecbWhat")}{" "}
              <a href="https://data.ecb.europa.eu/" target="_blank" rel="noreferrer">
                {t("footer.ecbPortal")}
              </a>
            </li>
            <li>
              <a href="https://www.cba.am/en" target="_blank" rel="noreferrer">
                {t("footer.cba")}
              </a>{" "}
              &middot; {t("footer.cbaWhat")}
            </li>
            <li>
              <a href="https://fred.stlouisfed.org/" target="_blank" rel="noreferrer">
                {t("footer.fred")}
              </a>{" "}
              &middot; {t("footer.fredWhat")}
            </li>
            <li>
              <a href="https://frankfurter.dev/" target="_blank" rel="noreferrer">
                Frankfurter
              </a>{" "}
              &middot; {t("footer.frankfurterWhat")}
            </li>
            <li>
              <a href="https://rate.am/" target="_blank" rel="noreferrer">
                rate.am
              </a>{" "}
              &middot; {t("footer.rateamWhat")}
            </li>
          </ul>
        </div>
        <div className="footer-meta">
          <p>
            {t("disclaimer")} {t("footer.calibrated")}
          </p>
          {manualTheme && (
            <button type="button" className="link-button" onClick={onResetTheme}>
              {t("footer.systemTheme")}
            </button>
          )}
        </div>
      </div>
    </footer>
  );
}
