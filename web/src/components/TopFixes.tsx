import type { RemediationEntry } from "../api";
import { effortStyle, formatPoints } from "../format";

interface TopFixesProps {
  plan: RemediationEntry[];
}

/** Up to five ranked remediation cards: score gain, effort class, action. */
export function TopFixes({ plan }: TopFixesProps) {
  const top = plan.slice(0, 5);
  if (top.length === 0) return null;

  return (
    <section aria-label="Top fixes">
      <h2 className="mb-3 text-base font-semibold">Top fixes</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {top.map((entry) => (
          <article
            key={entry.rule_id}
            className="card flex flex-col gap-3 p-4 transition hover:-translate-y-0.5 hover:shadow-card-md"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center rounded-full bg-brand px-2.5 py-0.5 text-xs font-semibold text-white">
                +{formatPoints(entry.score_gain)} pts
              </span>
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${effortStyle(entry.effort)}`}
              >
                {entry.effort}
              </span>
            </div>
            <p className="text-sm text-gray-700 dark:text-night-text">{entry.action}</p>
            <p className="mt-auto font-mono text-xs text-gray-400 dark:text-gray-500">
              {entry.rule_id}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default TopFixes;
