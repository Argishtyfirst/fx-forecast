import { DISCLAIMER } from "../lib/constants";

/** Shown on every forecast (spec: Frontend rules; Risks: "Users read the center as a promise"). */
export function Disclaimer({ text }: { text?: string | null }) {
  return (
    <p className="disclaimer" data-testid="disclaimer">
      {text || DISCLAIMER}
    </p>
  );
}
