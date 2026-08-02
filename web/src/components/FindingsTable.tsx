import { Fragment, useMemo, useState } from "react";
import type { Finding, SeverityLevel } from "../api";
import { SEVERITY_LABELS, truncateMiddle } from "../format";

type FilterTab = "all" | SeverityLevel;

const TABS: { id: FilterTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "error", label: "Errors" },
  { id: "warning", label: "Warnings" },
  { id: "info", label: "Info" },
];

const SEVERITY_CHIP: Record<SeverityLevel, { dot: string; chip: string }> = {
  error: {
    dot: "bg-danger-500",
    chip: "bg-danger-50 text-danger-700 dark:bg-red-500/10 dark:text-red-300",
  },
  warning: {
    dot: "bg-warning-500",
    chip: "bg-warning-50 text-warning-700 dark:bg-amber-500/10 dark:text-amber-300",
  },
  info: {
    dot: "bg-brandblue",
    chip: "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  },
};

function SeverityChip({ severity }: { severity: SeverityLevel }) {
  const style = SEVERITY_CHIP[severity];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${style.chip}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} aria-hidden="true" />
      {SEVERITY_LABELS[severity]}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-brand shadow-card-md">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m5 13 4 4L19 7" />
        </svg>
      </span>
      <p className="text-base font-semibold text-gray-900 dark:text-night-text">
        No findings &mdash; agent-native.
      </p>
      <p className="text-sm text-gray-500 dark:text-night-muted">
        Every applicable rule passed. This repository is ready for AI agents.
      </p>
    </div>
  );
}

interface FindingsTableProps {
  findings: Finding[];
}

export function FindingsTable({ findings }: FindingsTableProps) {
  const [filter, setFilter] = useState<FilterTab>("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  const counts = useMemo(() => {
    const map: Record<FilterTab, number> = { all: findings.length, error: 0, warning: 0, info: 0 };
    for (const finding of findings) map[finding.severity] += 1;
    return map;
  }, [findings]);

  const visible = useMemo(
    () => (filter === "all" ? findings : findings.filter((f) => f.severity === filter)),
    [findings, filter],
  );

  return (
    <section className="card p-6" aria-label="Findings">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Findings</h2>
        <div
          role="group"
          aria-label="Filter findings by severity"
          className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1 dark:border-night-border dark:bg-night-page"
        >
          {TABS.map((tab) => {
            const active = filter === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setFilter(tab.id);
                  setExpanded(null);
                }}
                className={`focus-ring rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  active
                    ? "bg-white text-gray-900 shadow-card dark:bg-night-card dark:text-night-text"
                    : "text-gray-500 hover:text-gray-700 dark:text-night-muted dark:hover:text-night-text"
                }`}
              >
                {tab.label}
                <span className="ml-1 text-gray-400 dark:text-gray-500">{counts[tab.id]}</span>
              </button>
            );
          })}
        </div>
      </div>

      {findings.length === 0 ? (
        <EmptyState />
      ) : visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-500 dark:text-night-muted">
          No {filter} findings.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-night-border">
          {visible.map((finding, index) => {
            const isOpen = expanded === index;
            const hasDetails = Boolean(finding.why || finding.fix || finding.doc_url);
            const location =
              finding.path !== null
                ? `${truncateMiddle(finding.path)}${finding.line !== null ? `:${finding.line}` : ""}`
                : "repository";
            return (
              <li key={`${finding.rule_id}-${finding.path ?? ""}-${finding.line ?? 0}-${index}`}>
                <button
                  type="button"
                  onClick={() => hasDetails && setExpanded(isOpen ? null : index)}
                  aria-expanded={hasDetails ? isOpen : undefined}
                  disabled={!hasDetails}
                  className={`focus-ring grid w-full grid-cols-[6.5rem_1fr_auto] items-start gap-x-3 gap-y-1 rounded-lg px-2 py-3 text-left sm:grid-cols-[6.5rem_10rem_1fr_auto] ${
                    hasDetails ? "cursor-pointer hover:bg-gray-50 dark:hover:bg-night-border/40" : "cursor-default"
                  }`}
                >
                  <SeverityChip severity={finding.severity} />
                  <span className="font-mono text-[13px] text-primary-700 dark:text-primary-400">
                    {finding.rule_id}
                  </span>
                  <span className="col-span-3 sm:col-span-1">
                    <span className="block text-sm text-gray-700 dark:text-night-text">
                      {finding.message}
                    </span>
                    <span className="mt-0.5 block font-mono text-xs text-gray-400 dark:text-gray-500">
                      {location}
                    </span>
                  </span>
                  {hasDetails && (
                    <svg
                      viewBox="0 0 20 20"
                      width="16"
                      height="16"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                      className={`mt-1 justify-self-end text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
                    >
                      <path d="m5 7.5 5 5 5-5" />
                    </svg>
                  )}
                </button>
                {isOpen && (
                  <div className="mb-3 ml-2 rounded-lg bg-gray-50 p-4 text-sm dark:bg-night-page">
                    {finding.why && (
                      <Fragment>
                        <p className="font-medium text-gray-900 dark:text-night-text">Why it matters</p>
                        <p className="mb-3 mt-1 text-gray-600 dark:text-night-muted">{finding.why}</p>
                      </Fragment>
                    )}
                    {finding.fix && (
                      <Fragment>
                        <p className="font-medium text-gray-900 dark:text-night-text">How to fix</p>
                        <p className="mt-1 text-gray-600 dark:text-night-muted">{finding.fix}</p>
                      </Fragment>
                    )}
                    {finding.doc_url && (
                      <Fragment>
                        <p className="mt-3 font-medium text-gray-900 dark:text-night-text">Source</p>
                        <a
                          href={finding.doc_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="focus-ring mt-1 inline-block break-all text-primary-700 underline hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-300"
                        >
                          {finding.doc_url}
                        </a>
                      </Fragment>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default FindingsTable;
