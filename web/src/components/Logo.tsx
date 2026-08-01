import { useId } from "react";

interface LogoProps {
  /** Height of the compass mark in px (wordmark scales with it). */
  size?: number;
  withTagline?: boolean;
  /** Render only the compass mark, no wordmark. */
  markOnly?: boolean;
}

/**
 * CodeCompass logo: gradient compass rose (8 directional wedges — large
 * cardinals, small diagonals), inner ring, two-kite needle rotated 45deg
 * with a center dot; wordmark "Code" (neutral) + "Compass" (gradient).
 */
export function Logo({ size = 40, withTagline = false, markOnly = false }: LogoProps) {
  const gradientId = useId();
  const wordmarkSize = Math.round(size * 0.62);

  const mark = (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      role="img"
      aria-label="CodeCompass logo"
      className="shrink-0 text-gray-900 dark:text-white"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#2970FF" />
          <stop offset="1" stopColor="#7F56D9" />
        </linearGradient>
      </defs>
      {/* Compass rose: 4 large cardinal wedges + 4 small diagonal wedges */}
      <g fill={`url(#${gradientId})`}>
        {[0, 90, 180, 270].map((angle) => (
          <path
            key={`cardinal-${angle}`}
            d="M24 1 L27.4 12.6 L24 10.9 L20.6 12.6 Z"
            transform={`rotate(${angle} 24 24)`}
          />
        ))}
        {[45, 135, 225, 315].map((angle) => (
          <path
            key={`diagonal-${angle}`}
            d="M24 6.5 L26.5 14.4 L24 13.2 L21.5 14.4 Z"
            transform={`rotate(${angle} 24 24)`}
          />
        ))}
      </g>
      {/* Inner ring */}
      <circle
        cx="24"
        cy="24"
        r="9.75"
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.5"
      />
      {/* Needle: two mirrored kites rotated 45deg (dark in light mode, white in dark) */}
      <g transform="rotate(45 24 24)" fill="currentColor">
        <path d="M24 16.5 L26.2 24 L24 22.9 L21.8 24 Z" />
        <path d="M24 31.5 L26.2 24 L24 25.1 L21.8 24 Z" opacity="0.55" />
      </g>
      <circle cx="24" cy="24" r="1.9" fill={`url(#${gradientId})`} />
    </svg>
  );

  if (markOnly) return mark;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex items-center gap-3">
        {mark}
        <span
          className="font-bold leading-none tracking-tight"
          style={{ fontSize: wordmarkSize }}
        >
          <span className="text-gray-900 dark:text-white">Code</span>
          <span className="text-gradient">Compass</span>
        </span>
      </div>
      {withTagline && (
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-gray-500 dark:text-night-muted">
          AI-powered repository understanding
        </p>
      )}
    </div>
  );
}

export default Logo;
