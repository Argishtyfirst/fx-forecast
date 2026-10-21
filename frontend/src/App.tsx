import { useEffect } from "react";
import { api, USE_MOCKS } from "./api/client";
import { Footer } from "./components/Footer";
import { MoonIcon, SunIcon } from "./components/Icons";
import { PAIR_IDS, PAIRS, VIEWS } from "./lib/constants";
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
  }, [route.pair, route.view]);

  return (
    <HealthContext.Provider value={health}>
      {USE_MOCKS && (
        <div className="mock-banner" role="note" data-testid="mock-banner">
          Mock mode. Every number on this page comes from fixture files in src/mocks, not from the API.
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
            {USE_MOCKS && <span className="tag tag-warn">Mock data</span>}
            <button
              type="button"
              className="icon-button"
              onClick={toggle}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Light mode" : "Dark mode"}
              data-testid="theme-toggle"
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
          </div>
        </div>
        <nav className="container header-nav" aria-label="Pair and view">
          <div className="segmented" role="group" aria-label="Currency pair">
            {PAIR_IDS.map((id) => (
              <a
                key={id}
                href={routeHref({ ...route, pair: id })}
                className={route.pair === id ? "seg seg-active" : "seg"}
                aria-current={route.pair === id ? "page" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  navigate({ pair: id });
                }}
              >
                {PAIRS[id].label}
              </a>
            ))}
          </div>
          <div className="tabs" role="group" aria-label="View">
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
    </HealthContext.Provider>
  );
}
