import type { AiStrength, SignalAction } from "../api/types";
import { t } from "../i18n";

/** The plain-word verdict. A slight lean (2 to 5 points) reads "Leaning sell now". */
export function verdictText(lean: SignalAction, strength?: AiStrength): string {
  if (lean === "no_edge") return t("verdict.no_edge");
  if (strength === "slight") return t(lean === "sell_now" ? "verdict.slight.sell_now" : "verdict.slight.wait");
  return t(lean === "sell_now" ? "verdict.sell_now" : "verdict.wait");
}
