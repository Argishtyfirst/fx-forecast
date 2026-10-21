import { useLayoutEffect, useRef, useState } from "react";

/**
 * Measures an element's content width. Falls back to `fallback` where ResizeObserver is missing
 * (jsdom), so charts still render in unit tests.
 */
export function useWidth<T extends HTMLElement>(fallback = 800): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof ResizeObserver === "undefined") {
      setWidth(el.clientWidth || fallback);
      return;
    }
    const measure = () => setWidth(Math.floor(el.getBoundingClientRect().width) || fallback);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);

  return [ref, width];
}
