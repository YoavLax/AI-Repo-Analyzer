import { useEffect, useId, useState } from "react";
import type { Score } from "../api";
import { gradeColor } from "../format";

interface ScoreRingProps {
  score: Score;
}

const RADIUS = 62;
const STROKE = 11;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * SVG radial gauge: 0-100 arc with the signature gradient, grade letter
 * inside. The arc draws in from empty on mount/score-change (via a
 * transitioned strokeDashoffset) and sits over a grade-tinted glow instead
 * of a flat card background.
 */
export function ScoreRing({ score }: ScoreRingProps) {
  const gradientId = useId();
  const overall = Math.max(0, Math.min(100, score.overall));
  const target = (overall / 100) * CIRCUMFERENCE;
  const color = gradeColor(score.grade);
  const box = (RADIUS + STROKE) * 2;

  // Starts fully "empty" (offset = full circumference) and animates to the
  // target offset once mounted, so the ring visibly draws in each time a
  // new report arrives. Respects prefers-reduced-motion via the CSS
  // transition-duration override in styles.css.
  const [offset, setOffset] = useState(CIRCUMFERENCE);
  useEffect(() => {
    setOffset(CIRCUMFERENCE);
    const frame = requestAnimationFrame(() => setOffset(CIRCUMFERENCE - target));
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return (
    <div className="flex flex-col items-center gap-3">
      <div
        role="img"
        aria-label={`Overall AI-readiness score ${Math.round(overall)} out of 100, grade ${score.grade}`}
        className="relative"
      >
        <div
          className="absolute inset-0 -z-10 rounded-full blur-2xl"
          style={{ background: `radial-gradient(circle, ${color}33, transparent 70%)` }}
          aria-hidden="true"
        />
        <svg width={box} height={box} viewBox={`0 0 ${box} ${box}`} aria-hidden="true">
          <defs>
            <linearGradient id={gradientId} x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor="#2970FF" />
              <stop offset="1" stopColor="#7F56D9" />
            </linearGradient>
          </defs>
          <circle
            cx={box / 2}
            cy={box / 2}
            r={RADIUS}
            fill="none"
            strokeWidth={STROKE}
            className="stroke-gray-100 dark:stroke-night-border"
          />
          <circle
            cx={box / 2}
            cy={box / 2}
            r={RADIUS}
            fill="none"
            stroke={`url(#${gradientId})`}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            className="transition-[stroke-dashoffset] duration-1000 ease-out"
            transform={`rotate(-90 ${box / 2} ${box / 2})`}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-5xl font-bold leading-none" style={{ color }}>
            {score.grade}
          </span>
          <span className="mt-1 text-sm font-medium text-gray-500 dark:text-night-muted">
            {Math.round(overall)} / 100
          </span>
        </div>
      </div>
      {score.grade_capped && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-50 px-2.5 py-0.5 text-xs font-medium text-warning-700 dark:bg-amber-500/10 dark:text-amber-300">
          <svg viewBox="0 0 12 12" width="12" height="12" fill="currentColor" aria-hidden="true">
            <path d="M6 1 11 10H1L6 1Zm-.6 3.5v2.8h1.2V4.5H5.4Zm0 3.8v1.2h1.2V8.3H5.4Z" />
          </svg>
          capped from {score.raw_grade}
        </span>
      )}
    </div>
  );
}

export default ScoreRing;
