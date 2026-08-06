import { ComponentType, useEffect, useRef, useState } from "react";
import type { AnalysisPhase, AnalysisProgress } from "../api";

/** How long one scene (art + joke) stays on screen. */
const SCENE_MS = 4200;

/**
 * Where each phase sits on the bar. The widths are proportional to what the
 * phases actually cost — fetching is the overwhelming majority of a scan (a
 * 1,134-file repository spends ~95% of its wall clock there), so it owns most
 * of the bar and the rest are the thin slivers they really are. Inside a phase
 * the position is `done / total`, both measured by the server.
 */
const PHASE_BANDS: Record<AnalysisPhase, readonly [number, number]> = {
  resolving: [0, 0.03],
  listing: [0.03, 0.06],
  fetching: [0.06, 0.88],
  linked: [0.88, 0.95],
  scoring: [0.95, 0.99],
};

function fillRatio(progress: AnalysisProgress): number {
  const band = PHASE_BANDS[progress.phase];
  if (!band) return 0;
  const [start, end] = band;
  const within = progress.total > 0 ? Math.min(1, progress.done / progress.total) : 0;
  return start + (end - start) * within;
}

/** The status line, stating what the server is actually doing right now. */
function stageLabel(progress: AnalysisProgress): string {
  const { phase, done, total } = progress;
  switch (phase) {
    case "resolving":
      return "Resolving the branch and pinning the commit";
    case "listing":
      return `${total.toLocaleString()} files listed — no clone, GitHub API only`;
    case "fetching":
      return `Fetching agent artifacts — ${done.toLocaleString()} of ${total.toLocaleString()}`;
    case "linked":
      return `Fetching linked docs — ${done.toLocaleString()} of ${total.toLocaleString()}`;
    case "scoring":
      return "Scoring pillars against the deterministic rule catalog";
  }
}

/* -------------------------------------------------------------------------- */
/*  Scene art — inline SVG only. No external assets: the deployed page is       */
/*  served under a strict CSP and has to render offline and in both themes.     */
/* -------------------------------------------------------------------------- */

const artClass = "h-24 w-24 shrink-0";

function CompassArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <circle cx="48" cy="48" r="43" className="stroke-primary-600/20 dark:stroke-primary-400/20" strokeWidth="2" strokeDasharray="3 8" />
      <circle cx="48" cy="48" r="33" className="stroke-primary-600/40 dark:stroke-primary-400/40" strokeWidth="3" />
      <g className="art-anim art-spin">
        <path d="M48 20 56 48 48 44 40 48Z" className="fill-brandblue" />
        <path d="M48 76 56 48 48 52 40 48Z" className="fill-primary-600 dark:fill-primary-400" />
      </g>
      <circle cx="48" cy="48" r="4.5" strokeWidth="2.5" className="fill-white stroke-primary-600 dark:fill-night-card dark:stroke-primary-400" />
    </svg>
  );
}

function RadarArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <circle cx="48" cy="48" r="40" className="stroke-primary-600/25 dark:stroke-primary-400/25" strokeWidth="2" />
      <circle cx="48" cy="48" r="26" className="stroke-primary-600/25 dark:stroke-primary-400/25" strokeWidth="2" />
      <circle cx="48" cy="48" r="12" className="stroke-primary-600/25 dark:stroke-primary-400/25" strokeWidth="2" />
      <g className="art-anim art-sweep">
        <path d="M48 48 48 8 A40 40 0 0 1 76 20Z" className="fill-brandblue/35" />
        <path d="M48 48 48 8" className="stroke-brandblue" strokeWidth="2.5" strokeLinecap="round" />
      </g>
      <circle cx="66" cy="34" r="3.5" className="art-pulse fill-primary-600 dark:fill-primary-400" />
      <circle cx="34" cy="62" r="2.5" className="fill-primary-600/60 dark:fill-primary-400/60" />
    </svg>
  );
}

function RobotArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <path d="M48 14v10" className="stroke-primary-600 dark:stroke-primary-400" strokeWidth="3" strokeLinecap="round" />
      <circle cx="48" cy="12" r="4" className="fill-brandblue" />
      <rect x="22" y="24" width="52" height="40" rx="12" strokeWidth="3" className="fill-white stroke-primary-600 dark:fill-night-card dark:stroke-primary-400" />
      <g className="art-blink">
        <circle cx="38" cy="42" r="4.5" className="fill-brandblue" />
        <circle cx="58" cy="42" r="4.5" className="fill-brandblue" />
      </g>
      <path d="M40 54h16" className="stroke-primary-600/50 dark:stroke-primary-400/50" strokeWidth="3" strokeLinecap="round" />
      <g className="art-anim art-bob">
        <rect x="30" y="70" width="36" height="16" rx="3" strokeWidth="3" className="fill-white stroke-primary-600/60 dark:fill-night-card dark:stroke-primary-400/60" />
        <path d="M36 76h18M36 81h12" className="stroke-primary-600/50 dark:stroke-primary-400/50" strokeWidth="2.5" strokeLinecap="round" />
      </g>
    </svg>
  );
}

function MagnifierArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <rect x="16" y="20" width="42" height="54" rx="5" strokeWidth="3" className="fill-white stroke-primary-600/45 dark:fill-night-card dark:stroke-primary-400/45" />
      <path d="M26 34h22M26 44h22M26 54h14" className="stroke-primary-600/40 dark:stroke-primary-400/40" strokeWidth="2.5" strokeLinecap="round" />
      <g className="art-anim art-bob">
        <circle cx="60" cy="52" r="18" strokeWidth="4" className="fill-brandblue/10 stroke-brandblue" />
        <path d="M73 65 84 76" className="stroke-primary-600 dark:stroke-primary-400" strokeWidth="5" strokeLinecap="round" />
      </g>
    </svg>
  );
}

function TerminalArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <rect x="10" y="20" width="76" height="56" rx="7" strokeWidth="3" className="fill-white stroke-primary-600/50 dark:fill-night-card dark:stroke-primary-400/50" />
      <path d="M10 33h76" className="stroke-primary-600/35 dark:stroke-primary-400/35" strokeWidth="2.5" />
      <circle cx="20" cy="26.5" r="2.5" className="fill-danger-500" />
      <circle cx="29" cy="26.5" r="2.5" className="fill-warning-500" />
      <circle cx="38" cy="26.5" r="2.5" className="fill-success-500" />
      <path d="M22 47l8 7-8 7" className="stroke-brandblue" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="38" y="50" width="22" height="4" rx="2" className="art-blink fill-primary-600 dark:fill-primary-400" />
    </svg>
  );
}

function ScalesArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <path d="M48 20v56M32 78h32" className="stroke-primary-600 dark:stroke-primary-400" strokeWidth="3.5" strokeLinecap="round" />
      <circle cx="48" cy="18" r="4" className="fill-brandblue" />
      <g className="art-anim art-tilt">
        <path d="M22 32h52" className="stroke-primary-600 dark:stroke-primary-400" strokeWidth="3.5" strokeLinecap="round" />
        <path d="M22 32 14 50h16Z" className="fill-brandblue/25 stroke-brandblue" strokeWidth="2.5" strokeLinejoin="round" />
        <path d="M74 32 66 50h16Z" className="fill-primary-600/25 stroke-primary-600 dark:stroke-primary-400" strokeWidth="2.5" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

function NoteArt() {
  return (
    <svg viewBox="0 0 96 96" className={artClass} fill="none">
      <g className="art-anim art-tilt">
        <rect x="18" y="22" width="44" height="44" rx="4" strokeWidth="3" className="fill-warning-50 stroke-warning-500 dark:fill-warning-500/10" />
        <path d="M27 35h26M27 44h26M27 53h16" className="stroke-warning-700 dark:stroke-warning-500" strokeWidth="2.5" strokeLinecap="round" />
      </g>
      <g className="art-anim art-bob">
        <rect x="42" y="40" width="40" height="40" rx="4" strokeWidth="3" className="fill-white stroke-primary-600/60 dark:fill-night-card dark:stroke-primary-400/60" />
        <path d="M50 53h24M50 62h24M50 71h14" className="stroke-primary-600/50 dark:stroke-primary-400/50" strokeWidth="2.5" strokeLinecap="round" />
      </g>
    </svg>
  );
}

/** Art paired deliberately with its line — the joke and the picture are one
 *  scene, so they rotate together rather than on independent timers. */
const SCENES: { art: ComponentType; joke: string }[] = [
  { art: CompassArt, joke: "Orienting the needle. North is wherever your docs actually are." },
  { art: RadarArt, joke: "Sweeping for agent artifacts. No clone — just the GitHub API and good manners." },
  { art: RobotArt, joke: "Reading your CLAUDE.md so your agent doesn't have to guess." },
  { art: MagnifierArt, joke: "Every repository claims it has documentation. We check." },
  { art: TerminalArt, joke: "Gently informing the linter that “vibes” is not a rule." },
  { art: ScalesArt, joke: "Weighing what your README promises against what the repo ships." },
  { art: NoteArt, joke: "Your agents left notes for each other. We're reading them." },
];

/* -------------------------------------------------------------------------- */

/** Milliseconds since mount, ticking often enough for the bar to look smooth. */
function useElapsedMs(): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const id = setInterval(() => setElapsed(performance.now() - start), 120);
    return () => clearInterval(id);
  }, []);
  return elapsed;
}

function ProgressPanel({ progress }: { progress: AnalysisProgress | null }) {
  const elapsed = useElapsedMs();
  const sceneIndex = Math.floor(elapsed / SCENE_MS) % SCENES.length;
  const scene = SCENES[sceneIndex] ?? SCENES[0]!;
  const Art = scene.art;
  const seconds = Math.floor(elapsed / 1000);

  // The bar only ever moves forward. Phases are ordered so this holds already,
  // but a retried or reordered event must not make it jump backwards, which
  // reads as the analysis losing ground.
  const highWater = useRef(0);
  const ratio = progress ? Math.max(highWater.current, fillRatio(progress)) : 0;
  highWater.current = ratio;

  const percent = Math.round(ratio * 100);
  const label = progress
    ? stageLabel(progress)
    : "Connecting to the analyzer…";

  return (
    <div className="card mb-6 flex flex-col items-center gap-5 px-4 py-8 sm:px-8">
      <div key={sceneIndex} className="scene-in flex flex-col items-center gap-4" aria-hidden="true">
        <Art />
        <p className="max-w-md text-balance text-center text-sm font-medium text-gray-700 dark:text-night-text">
          {scene.joke}
        </p>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        // Present only once the server has reported something. Before that the
        // amount really is unknown, and ARIA says an indeterminate progressbar
        // omits the value rather than guessing at one.
        aria-valuenow={progress ? percent : undefined}
        aria-valuetext={progress ? `${percent}% — ${label}` : label}
        className="h-2 w-full max-w-md overflow-hidden rounded-full bg-gray-100 dark:bg-night-border"
      >
        {progress ? (
          <div
            className="progress-sheen h-full rounded-full bg-brand transition-[width] duration-300 ease-out"
            style={{ width: `${(ratio * 100).toFixed(1)}%` }}
          />
        ) : (
          <div className="loading-bar h-full w-1/3 rounded-full bg-brand" />
        )}
      </div>

      <p
        role="status"
        aria-live="polite"
        className="flex flex-wrap items-center justify-center gap-x-2 text-center text-xs text-gray-500 dark:text-night-muted"
      >
        <span>{label}</span>
        <span className="font-mono tabular-nums text-gray-400 dark:text-gray-500">
          {progress ? `${percent}% · ${seconds}s` : `${seconds}s`}
        </span>
      </p>
    </div>
  );
}

interface LoadingSkeletonProps {
  /** Server-reported progress; null until the first event of a run arrives. */
  progress?: AnalysisProgress | null;
}

/** Skeleton dashboard shown while the analysis request is in flight. */
export function LoadingSkeleton({ progress = null }: LoadingSkeletonProps) {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-10" aria-busy="true">
      <ProgressPanel progress={progress} />

      <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
        {/* Score ring placeholder */}
        <div className="card flex items-center justify-center p-6">
          <div className="skeleton h-36 w-36 rounded-full" />
        </div>
        {/* Stat cards */}
        <div className="grid grid-cols-1 gap-4 min-[420px]:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card flex flex-col justify-center gap-3 p-5">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton h-8 w-14" />
            </div>
          ))}
        </div>
      </div>

      {/* Pillar table placeholder */}
      <div className="card mt-4 p-6">
        <div className="skeleton mb-5 h-4 w-24" />
        <div className="space-y-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="skeleton h-3 w-28 shrink-0" />
              <div className="skeleton h-2.5 min-w-0 flex-1" />
              <div className="skeleton h-3 w-10 shrink-0" />
            </div>
          ))}
        </div>
      </div>

      {/* Findings placeholder */}
      <div className="card mt-4 p-6">
        <div className="skeleton mb-5 h-4 w-32" />
        <div className="space-y-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton h-9 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

export default LoadingSkeleton;
