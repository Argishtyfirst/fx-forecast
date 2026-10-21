import { useCallback, useEffect, useState } from "react";
import type { PairId } from "../api/types";
import { isPairId, VIEWS, type ViewId } from "./constants";

/** URL-addressable state: #/{view}/{pair}[/{detail}], e.g. #/pair/EURUSD or #/drivers/USDAMD/1M. */
export interface Route {
  view: ViewId;
  pair: PairId;
  detail?: string;
}

export const DEFAULT_ROUTE: Route = { view: "pair", pair: "EURAMD" };

export function parseHash(hash: string): Route {
  const [view, pair, detail] = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const v = VIEWS.find((x) => x.id === view)?.id;
  if (!v) return DEFAULT_ROUTE;
  return {
    view: v,
    pair: isPairId(pair?.toUpperCase()) ? (pair.toUpperCase() as PairId) : DEFAULT_ROUTE.pair,
    detail: detail || undefined,
  };
}

export function routeHref(r: Route): string {
  return `#/${r.view}/${r.pair}${r.detail ? `/${r.detail}` : ""}`;
}

export function useRoute(): [Route, (next: Partial<Route>, opts?: { replace?: boolean }) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    // Normalise an empty or invalid hash to the canonical form.
    const canonical = routeHref(parseHash(window.location.hash));
    if (window.location.hash !== canonical) window.history.replaceState(null, "", canonical);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, []);

  const navigate = useCallback(
    (next: Partial<Route>, opts?: { replace?: boolean }) => {
      setRoute((cur) => {
        const merged: Route = { ...cur, ...next };
        // A new view starts without the previous view's detail segment.
        if (next.view && next.view !== cur.view && !("detail" in next)) merged.detail = undefined;
        const href = routeHref(merged);
        if (window.location.hash !== href) {
          if (opts?.replace) window.history.replaceState(null, "", href);
          else window.history.pushState(null, "", href);
        }
        return merged;
      });
    },
    [],
  );

  return [route, navigate];
}
