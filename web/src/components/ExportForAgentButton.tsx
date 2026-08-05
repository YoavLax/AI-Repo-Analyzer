import { useState } from "react";
import type { Report } from "../api";
import { downloadAgentFixExport } from "../agentExport";
import { formatScore } from "../format";

interface ExportForAgentButtonProps {
  report: Report;
}

function DownloadIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 3.5v11m0 0-3.5-3.5M12 14.5 15.5 11M5 17.5v1.75A1.75 1.75 0 0 0 6.75 21h10.5A1.75 1.75 0 0 0 19 19.25V17.5" />
    </svg>
  );
}

/**
 * Exports the full report (findings + remediation plan, with why/how/source
 * for each) as a single JSON file the user can hand to their coding agent.
 */
export function ExportForAgentButton({ report }: ExportForAgentButtonProps) {
  const [justExported, setJustExported] = useState(false);
  const hasFindings = report.findings.length > 0;

  function handleExport() {
    downloadAgentFixExport(report);
    setJustExported(true);
    window.setTimeout(() => setJustExported(false), 2500);
  }

  return (
    <section
      aria-label="Export findings for your AI agent"
      className="card flex flex-col items-start gap-4 border-primary-200/70 bg-gradient-to-br from-primary-50/70 via-white to-white p-5 dark:border-primary-500/20 dark:from-primary-500/10 dark:via-night-card dark:to-night-card sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-white shadow-card"
          aria-hidden="true"
        >
          <DownloadIcon />
        </span>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-night-text">
            Let your agent finish the job
          </p>
          <p className="mt-0.5 max-w-xl text-sm text-gray-600 dark:text-night-muted">
            {hasFindings ? (
              <>
                Export every warning, error, and recommendation as one JSON file. 
                Just give it to your agent and it&apos;ll make your score rise from {formatScore(report.score.overall)} to 100.
              </>
            ) : (
              "No open findings \u2014 this repository already scores 100 on every applicable rule."
            )}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={handleExport}
        disabled={!hasFindings}
        className="focus-ring inline-flex h-10 shrink-0 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        <DownloadIcon />
        {justExported ? "Exported \u2713" : "Export for your agent"}
      </button>
    </section>
  );
}

export default ExportForAgentButton;
