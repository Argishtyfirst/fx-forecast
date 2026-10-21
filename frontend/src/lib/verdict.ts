import type { AiStrength, SignalAction } from "../api/types";

/** The plain-word verdict. A slight lean (2 to 5 points) reads "Leaning sell now". */
export function verdictText(lean: SignalAction, strength?: AiStrength): string {
  if (lean === "no_edge") return "No clear answer";
  const word = lean === "sell_now" ? "Sell now" : "Wait";
  return strength === "slight" ? `Leaning ${word.toLowerCase()}` : word;
}
