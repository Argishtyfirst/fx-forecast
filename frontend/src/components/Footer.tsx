import { DISCLAIMER } from "../lib/constants";

/** NFR-08: credit every data source. */
export function Footer({ onResetTheme, manualTheme }: { onResetTheme: () => void; manualTheme: boolean }) {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-sources">
          <p className="footer-title">Data sources</p>
          <ul>
            <li>
              <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html" target="_blank" rel="noreferrer">
                European Central Bank
              </a>{" "}
              &middot; euro reference rates, key ECB interest rates, &euro;STR and HICP via the{" "}
              <a href="https://data.ecb.europa.eu/" target="_blank" rel="noreferrer">
                ECB Data Portal
              </a>
            </li>
            <li>
              <a href="https://www.cba.am/en" target="_blank" rel="noreferrer">
                Central Bank of Armenia
              </a>{" "}
              &middot; AMD exchange rates, policy rates and Board decisions
            </li>
            <li>
              <a href="https://fred.stlouisfed.org/" target="_blank" rel="noreferrer">
                FRED, Federal Reserve Bank of St. Louis
              </a>{" "}
              &middot; Fed target range, rates, yields and the dollar index. This product uses the FRED&reg; API but
              is not endorsed or certified by the Federal Reserve Bank of St. Louis.
            </li>
            <li>
              <a href="https://frankfurter.dev/" target="_blank" rel="noreferrer">
                Frankfurter
              </a>{" "}
              &middot; open API for the ECB and CBA daily rates
            </li>
          </ul>
        </div>
        <div className="footer-meta">
          <p>{DISCLAIMER} Ranges are calibrated against walk-forward backtests; the center is not a promise.</p>
          {manualTheme && (
            <button type="button" className="link-button" onClick={onResetTheme}>
              Follow the system theme
            </button>
          )}
        </div>
      </div>
    </footer>
  );
}
