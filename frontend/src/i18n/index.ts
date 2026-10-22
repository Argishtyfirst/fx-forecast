/**
 * A small dictionary-based i18n: `t(key, vars)` with {name} placeholders and plural forms
 * chosen by Intl.PluralRules. The active language lives here (module state) so plain helper
 * functions can translate too; the app remounts its content when the language changes.
 * One file per language (en.ts, hy.ts, ru.ts) so a native speaker can review each in one place.
 */
import { useCallback, useState } from "react";
import { en, type Dict, type Entry, type Key } from "./en";
import { hy } from "./hy";
import { ru } from "./ru";

export type Lang = "en" | "hy" | "ru";
export type { Key };
export const LANGS: Lang[] = ["en", "hy", "ru"];
export const LOCALES: Record<Lang, string> = { en: "en-GB", hy: "hy-AM", ru: "ru-RU" };
const DICTS: Record<Lang, Dict> = { en, hy, ru };
const STORAGE_KEY = "fxf-lang";

function detect(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "hy" || saved === "ru") return saved;
  } catch {
    // Storage blocked: fall back to the browser language.
  }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "en").toLowerCase();
  if (nav.startsWith("hy")) return "hy";
  if (nav.startsWith("ru")) return "ru";
  return "en";
}

let current: Lang = typeof window !== "undefined" ? detect() : "en";
if (typeof document !== "undefined") document.documentElement.lang = current;

export function getLang(): Lang {
  return current;
}

export function getLocale(): string {
  return LOCALES[current];
}

export function setLang(lang: Lang): void {
  current = lang;
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Storage blocked: the choice holds for this session.
  }
}

type Vars = Record<string, string | number>;

function pick(entry: Entry, count: number | undefined): string {
  if (typeof entry === "string") return entry;
  const form = new Intl.PluralRules(LOCALES[current]).select(count ?? 0) as keyof typeof entry;
  return entry[form] ?? entry.other;
}

/** Translate `key`; `vars.count` (a number) chooses the plural form when the entry has forms. */
export function t(key: Key, vars?: Vars): string {
  const entry = DICTS[current][key] ?? en[key];
  const count = typeof vars?.count === "number" ? vars.count : undefined;
  return pick(entry, count).replace(/\{(\w+)\}/g, (m, name: string) =>
    vars && vars[name] !== undefined ? String(vars[name]) : m,
  );
}

/** Translate a key built at runtime (e.g. `bank.${id}`), or return null when it does not exist. */
export function tMaybe(key: string, vars?: Vars): string | null {
  return key in en ? t(key as Key, vars) : null;
}

/** Pick the active language's text from an {en, hy, ru} map, else the English fallback. */
export function pickText(map: Partial<Record<Lang, string | null>> | null | undefined, fallback: string): string {
  return map?.[current] || fallback;
}

/** React state for the language; setting it updates the module state and <html lang>. */
export function useLang(): [Lang, (l: Lang) => void] {
  const [lang, set] = useState<Lang>(current);
  const change = useCallback((l: Lang) => {
    setLang(l);
    set(l);
  }, []);
  return [lang, change];
}
