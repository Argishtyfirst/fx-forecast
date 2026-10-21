/** Small stroke icons drawn as SVG primitives (2px strokes, 16px grid). */

interface IconProps {
  size?: number;
  className?: string;
  title?: string;
}

function Svg({ size = 16, className, title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

export const WarningIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 2.2 14.3 13.2H1.7Z" />
    <path d="M8 6.4v3.1" />
    <circle cx="8" cy="11.4" r="0.35" fill="currentColor" />
  </Svg>
);

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m3.2 8.4 3 3 6.6-6.8" />
  </Svg>
);

export const CrossIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m4.2 4.2 7.6 7.6M11.8 4.2l-7.6 7.6" />
  </Svg>
);

export const MoonIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8Z" />
  </Svg>
);

export const SunIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="2.8" />
    <path d="M8 1.3v1.4M8 13.3v1.4M1.3 8h1.4M13.3 8h1.4M3.3 3.3l1 1M11.7 11.7l1 1M3.3 12.7l1-1M11.7 4.3l1-1" />
  </Svg>
);

export const ExternalIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 3.5h-3v9h9v-3M9.5 2.5h4v4M13.5 2.5 7.5 8.5" />
  </Svg>
);

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 3.5v9M3.5 8h9" />
  </Svg>
);

export const MinusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 8h9" />
  </Svg>
);

export const RetryIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v2.8h-2.8" />
  </Svg>
);
