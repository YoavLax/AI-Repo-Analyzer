import type { PillarScore } from "../api";

interface PillarTableProps {
  pillars: PillarScore[];
}

function pct(ratio: number | null): number {
  if (ratio === null) return 0;
  return Math.max(0, Math.min(100, ratio * 100));
}

function MiniBar({ label, ratio }: { label: string; ratio: number | null }) {
  return (
    <div className="flex shrink-0 items-center gap-1.5" title={`${label}: ${ratio === null ? "n/a" : `${Math.round(pct(ratio))}%`}`}>
      <span className="w-7 shrink-0 text-[11px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {label}
      </span>
      <div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-gray-100 dark:bg-night-border">
        <div
          className="h-full rounded-full bg-gray-400 dark:bg-gray-500"
          style={{ width: `${pct(ratio)}%` }}
        />
      </div>
    </div>
  );
}

/** One row per pillar: name, weight, gradient score bar, presence/quality mini-bars. */
export function PillarTable({ pillars }: PillarTableProps) {
  return (
    <section className="card p-6" aria-label="Pillar scores">
      <h2 className="mb-5 text-base font-semibold">Pillars</h2>
      <ul className="space-y-4">
        {pillars.map((pillar) => {
          const scored = pillar.score !== null;
          return (
            <li
              key={pillar.id}
              className="-mx-2 grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] items-center gap-x-4 gap-y-2 rounded-lg p-2 transition-colors hover:bg-gray-50 dark:hover:bg-night-border/30 sm:grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)_auto]"
            >
              <div className="min-w-0">
                <p
                  className={`text-sm font-medium capitalize [overflow-wrap:anywhere] ${
                    scored ? "text-gray-900 dark:text-night-text" : "text-gray-400 dark:text-gray-600"
                  }`}
                >
                  {pillar.id}
                </p>
                <p className="text-xs text-gray-400 dark:text-gray-500">weight {pillar.weight}</p>
              </div>

              {scored ? (
                <div className="flex min-w-0 items-center gap-3">
                  <div
                    role="meter"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(pct(pillar.score))}
                    aria-label={`${pillar.id} pillar score`}
                    className="h-2.5 flex-1 overflow-hidden rounded-full bg-gray-100 dark:bg-night-border"
                  >
                    <div
                      className="h-full rounded-full bg-brand"
                      style={{ width: `${pct(pillar.score)}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-sm font-medium text-gray-700 dark:text-night-text">
                    {Math.round(pct(pillar.score))}
                  </span>
                </div>
              ) : (
                <p className="text-sm italic text-gray-400 dark:text-gray-600">
                  not scored &mdash; no rules registered yet
                </p>
              )}

              {scored && (
                <div className="col-start-2 flex flex-wrap gap-x-4 gap-y-1 sm:col-start-3">
                  <MiniBar label="pre" ratio={pillar.presence_ratio} />
                  <MiniBar label="qua" ratio={pillar.quality_ratio} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default PillarTable;
