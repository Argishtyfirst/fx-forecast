/**
 * Icons come from one family, Phosphor (@phosphor-icons/react), at one weight across the app.
 * These wrappers keep the call sites short and the weight consistent.
 */
import {
  ArrowClockwise,
  ArrowSquareOut,
  Check,
  CheckCircle,
  HourglassMedium,
  Minus,
  Moon,
  Plus,
  Scales,
  Sun,
  Warning,
  X,
  type Icon,
} from "@phosphor-icons/react";

interface IconProps {
  size?: number;
  className?: string;
  /** Accessible name; without it the icon is decorative and hidden from assistive tech. */
  title?: string;
}

const WEIGHT = "bold" as const;

function wrap(Glyph: Icon) {
  return function AppIcon({ size = 16, className, title }: IconProps) {
    return (
      <Glyph
        size={size}
        weight={WEIGHT}
        className={className}
        alt={title}
        aria-hidden={title ? undefined : true}
        role={title ? "img" : undefined}
        focusable="false"
      />
    );
  };
}

export const WarningIcon = wrap(Warning);
export const CheckIcon = wrap(Check);
export const CrossIcon = wrap(X);
export const MoonIcon = wrap(Moon);
export const SunIcon = wrap(Sun);
export const ExternalIcon = wrap(ArrowSquareOut);
export const PlusIcon = wrap(Plus);
export const MinusIcon = wrap(Minus);
export const RetryIcon = wrap(ArrowClockwise);
/** Verdict glyphs: sell now, wait, no clear answer. */
export const SellNowIcon = wrap(CheckCircle);
export const WaitIcon = wrap(HourglassMedium);
export const UnclearIcon = wrap(Scales);
