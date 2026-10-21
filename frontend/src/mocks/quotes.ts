/**
 * Mock provider rates for GET /api/quotes/{pair}?amount= (AMD pairs only), shaped like the live
 * API on 21 Oct 2026: many banks tie at the same board rate, one bank has cash, account and card
 * rows, the Inecobank app is a separate "online" rate, and transfers from abroad cost more.
 */
import type { ProviderQuote, QuotesResponse } from "../api/types";

type Seed = [provider: string, name: string, kind: ProviderQuote["kind"], channel: ProviderQuote["channel"], perBase: number, feeBase: number, note: string | null, delivery: string | null, fetched: string];

const F = "2026-10-21T14:20:51Z";
// perBase is AMD per EUR on the provider board; USD/AMD scales it by the cross rate.
const SEEDS: Seed[] = [
  ["acba", "Acba bank", "bank", "non_cash", 401, 0, null, null, F],
  ["acba", "Acba bank", "bank", "card", 401, 0, null, null, F],
  ["acba", "Acba bank", "bank", "cash", 401, 0, null, null, F],
  ["converse", "Converse Bank", "bank", "non_cash", 401, 0, null, null, F],
  ["converse", "Converse Bank", "bank", "cash", 401, 0, null, null, F],
  ["vtb", "VTB Bank (Armenia)", "bank", "non_cash", 401, 0, null, null, F],
  ["artsakhbank", "Artsakhbank", "bank", "non_cash", 401, 0, null, null, F],
  ["inecobank", "Inecobank", "bank", "online", 400.77, 0, "Rate in InecoOnline and the Inecobank app", null, F],
  ["inecobank", "Inecobank", "bank", "non_cash", 400, 0, null, null, F],
  ["inecobank", "Inecobank", "bank", "cash", 400, 0, null, null, F],
  ["armswissbank", "ArmSwissBank", "bank", "non_cash", 400.5, 0, null, null, F],
  ["fastbank", "Fast Bank", "bank", "non_cash", 400.5, 0, null, null, F],
  ["evocabank", "Evocabank", "bank", "non_cash", 400, 0, null, null, F],
  ["evocabank", "Evocabank", "bank", "cash", 400, 0, null, null, F],
  ["unibank", "Unibank", "bank", "non_cash", 400, 0, null, null, F],
  ["ameriabank", "Ameriabank", "bank", "non_cash", 399, 0, null, null, F],
  ["ameriabank", "Ameriabank", "bank", "cash", 399, 0, null, null, F],
  ["ardshinbank", "Ardshinbank", "bank", "non_cash", 399, 0, null, null, F],
  ["ardshinbank", "Ardshinbank", "bank", "cash", 399, 0, null, null, F],
  ["paysend", "Paysend", "transfer", "transfer", 399.74, 1.5, "Card transfer from a European account to an Armenian card", "Should arrive: In a few minutes", F],
  ["wise", "Wise", "transfer", "transfer", 389.1, 4.9, "Bank transfer from a European account to an Armenian bank account by SWIFT", "2026-10-28T05:30:00Z", F],
  ["mellat", "Mellat Bank", "bank", "cash", 400, 0, null, null, "2026-10-19T08:30:00Z"],
];

const NOW = Date.parse("2026-10-21T16:00:00Z");

export function mockQuotes(pair: string, amount: number, reference: number, date: string): QuotesResponse {
  // Boards are quoted for EUR/AMD around a 405.92 CBA rate; scale them to this pair's reference.
  const k = reference / 405.92;
  const quotes = SEEDS.map(([provider, name, kind, channel, perBase, feeBase, note, delivery, fetched]): ProviderQuote => {
    const rate = Math.round(perBase * k * 100) / 100;
    const fee = Math.round(feeBase * rate * 100) / 100;
    const net = Math.round((amount * rate - fee) * 100) / 100;
    return {
      provider,
      name,
      kind,
      channel,
      rate,
      fee,
      net,
      vs_reference_pct: Math.round((net / (amount * reference) - 1) * 100000) / 1000,
      fetched_at: fetched,
      quoted_at: null,
      stale: NOW - Date.parse(fetched) > 26 * 3600_000,
      url: null,
      note,
      delivery,
    };
  }).sort((a, b) => Number(a.stale) - Number(b.stale) || b.net - a.net || a.name.localeCompare(b.name));
  return {
    pair,
    amount,
    reference: { source: "CBA", rate: reference, date },
    as_of: F,
    quotes,
    unavailable: [
      {
        provider: "revolut",
        name: "Revolut",
        reason:
          "Revolut does not publish its dram rate for automated reading. Check the app: you cannot hold dram there, so a transfer to Armenia converts when you send, and weekend exchanges cost 1% more.",
        url: "https://www.revolut.com/",
      },
    ],
    indicative: true,
    disclaimer:
      "Indicative rates collected from public pages, not offers. Banks may give a better rate for large amounts, and transfer services change fees often. Check with the provider before you convert.",
  };
}
