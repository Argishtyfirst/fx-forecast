import { useEffect } from "react";
import { api, USE_MOCKS } from "./api/client";
import { Footer } from "./components/Footer";
import { MoonIcon, SunIcon } from "./components/Icons";
import { LANGS, t, useLang, type Lang } from "./i18n";
import { BASES, PAIRS, QUOTES_FOR, VIEWS, pairOf } from "./lib/constants";
import { HealthContext } from "./lib/health";
import { routeHref, useRoute } from "./lib/route";
import { useTheme } from "./lib/theme";
import { useApi } from "./lib/useApi";
import { BacktestView } from "./views/BacktestView";
import { DriversView } from "./views/DriversView";
import { EventsView } from "./views/EventsView";
import { PairView } from "./views/PairView";

const HEALTH_REFRESH_MS = 5 * 60_000;

export function App() {
  const [route, navigate] = useRoute();
  const [lang, changeLang] = useLang();
  const { theme, manual, toggle, reset } = useTheme();
  const health = useApi("health", api.health);
  const { reload: reloadHealth } = health;

  useEffect(() => {
    const id = window.setInterval(reloadHealth, HEALTH_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [reloadHealth]);

  useEffect(() => {
    const view = VIEWS.find((v) => v.id === route.view)?.label ?? "";
    document.title = `${PAIRS[route.pair].label} ${view} · FX Forecast`;
  }, [route.pair, route.view, lang]);

  const current = PAIRS[route.pair];
  const choose = (base: string, quote: string) => {
    const valid = QUOTES_FOR[base] ?? [];
    const id = pairOf(base, valid.includes(quote) ? quote : valid[0]);
    if (id) navigate({ pair: id });
  };

  return (
    <HealthContext.Provider value={health}>
      <div className="app" key={lang}>
      {USE_MOCKS && (
        <div className="mock-banner" role="note" data-testid="mock-banner">
          {t("app.mockBanner")}
        </div>
      )}
      <header className="header">
        <div className="container header-top">
          <a className="brand" href={routeHref({ view: "pair", pair: route.pair })}>
            <svg className="brand-mark" viewBox="0 0 20 20" aria-hidden="true">
              <path d="M8 11 19 3v16Z" className="brand-95" />
              <path d="M8 11 19 6.5v9Z" className="brand-80" />
              <path d="M8 11 19 9v4Z" className="brand-50" />
              <path d="M1.5 12.2 8 11" className="brand-line" />
            </svg>
            <span className="brand-name">FX Forecast</span>
          </a>
          <div className="header-actions">
            {USE_MOCKS && <span className="tag tag-warn">{t("app.mockTag")}</span>}
            <LangSwitch lang={lang} onChange={changeLang} />
            <button
              type="button"
              className="icon-button"
              onClick={toggle}
              aria-label={theme === "dark" ? t("app.toLight") : t("app.toDark")}
              title={theme === "dark" ? t("app.light") : t("app.dark")}
              data-testid="theme-toggle"
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </div>
        <nav className="container header-nav" aria-label={t("app.navAria")}>
          <div className="pair-picker" role="group" aria-label={t("picker.aria")} data-testid="pair-picker">
            <label className="picker-field">
              <span className="picker-word">{t("picker.have")}</span>
              <select
                value={current.base}
                onChange={(e) => choose(e.target.value, current.quote)}
                aria-label={t("picker.haveAria")}
              >
                {BASES.map((b) => (
                  <option key={b} value={b}>
                    {b} · {t(`cur.${b}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="picker-field">
              <span className="picker-word">{t("picker.need")}</span>
              <select
                value={current.quote}
                onChange={(e) => choose(current.base, e.target.value)}
                aria-label={t("picker.needAria")}
              >
                {(QUOTES_FOR[current.base] ?? []).map((q) => (
                  <option key={q} value={q}>
                    {q} · {t(`cur.${q as "AMD" | "USD"}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="tabs" role="group" aria-label={t("app.viewAria")}>
            {VIEWS.map((v) => (
              <a
                key={v.id}
                aria-current={route.view === v.id ? "page" : undefined}
                href={routeHref({ view: v.id, pair: route.pair })}
                className={route.view === v.id ? "tab tab-active" : "tab"}
                onClick={(e) => {
                  e.preventDefault();
                  navigate({ view: v.id });
                }}
              >
                {v.label}
              </a>
            ))}
          </div>
        </nav>
      </header>

      <main className="container main" key={`${route.view}-${route.pair}`}>
        {route.view === "pair" && <PairView pair={route.pair} />}
        {route.view === "drivers" && (
          <DriversView
            pair={route.pair}
            horizon={route.detail}
            onHorizon={(label) => navigate({ detail: label }, { replace: true })}
          />
        )}
        {route.view === "events" && (
          <EventsView
            pair={route.pair}
            bank={route.detail}
            onBank={(bank) => navigate({ detail: bank }, { replace: true })}
          />
        )}
        {route.view === "backtest" && (
          <BacktestView
            pair={route.pair}
            window={route.detail}
            onWindow={(w) => navigate({ detail: w }, { replace: true })}
          />
        )}
      </main>
      <Footer onResetTheme={reset} manualTheme={manual} />
      </div>
    </HealthContext.Provider>
  );
}

const LANG_LABEL: Record<Lang, string> = { en: "EN", hy: "ՀԱՅ", ru: "РУ" };
const LANG_NAME: Record<Lang, string> = { en: "English", hy: "Հայերեն", ru: "Русский" };

/** EN / ՀԱՅ / РУ: a compact switch, each language named in itself for screen readers. */
function LangSwitch({ lang, onChange }: { lang: Lang; onChange: (l: Lang) => void }) {
  return (
    <div className="segmented lang-switch" role="group" aria-label={t("app.langAria")} data-testid="lang-switch">
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          className={l === lang ? "seg seg-active" : "seg"}
          aria-pressed={l === lang}
          aria-label={LANG_NAME[l]}
          onClick={() => onChange(l)}
        >
          {LANG_LABEL[l]}
        </button>
      ))}
    </div>
  );
}
