import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "fxf-theme";

function readStored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function writeStored(v: Theme | null): void {
  try {
    if (v) window.localStorage.setItem(KEY, v);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Storage can be blocked (private mode); the toggle still works for this session.
  }
}

function systemTheme(): Theme {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/** Follows prefers-color-scheme until the user picks a theme; the pick persists in localStorage. */
export function useTheme(): { theme: Theme; manual: boolean; toggle: () => void; reset: () => void } {
  const [stored, setStored] = useState<Theme | null>(() => readStored());
  const [system, setSystem] = useState<Theme>(() => systemTheme());

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (stored) root.dataset.theme = stored;
    else delete root.dataset.theme;
  }, [stored]);

  const theme = stored ?? system;
  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    writeStored(next);
    setStored(next);
  }, [theme]);
  const reset = useCallback(() => {
    writeStored(null);
    setStored(null);
  }, []);

  return { theme, manual: stored !== null, toggle, reset };
}
