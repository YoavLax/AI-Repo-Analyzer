import { FormEvent, useState } from "react";
import type { AnalyzeRequest, ApiError, PlatformFilter, Report } from "../api";
import { formatDelta, formatScore, shortSha } from "../format";
import type { Theme } from "../theme";
import ErrorState from "./ErrorState";
import FindingsTable from "./FindingsTable";
import Logo from "./Logo";
import PillarTable from "./PillarTable";
import PlatformToggle from "./PlatformToggle";
import ScoreRing from "./ScoreRing";
import ThemeToggle from "./ThemeToggle";
import TopFixes from "./TopFixes";
import WaiversPanel from "./WaiversPanel";

const PLATFORM_LABEL: Record<PlatformFilter, string> = {
  all: "All",
  copilot: "Copilot",
  claude: "Claude Code",
};

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        className="opacity-90"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4Z"
      />
    </svg>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card flex flex-col justify-center gap-1 p-5">
      <p className="text-[13px] font-medium text-gray-500 dark:text-night-muted">{label}</p>
      <p className="text-3xl font-semibold text-gray-900 dark:text-night-text">{value}</p>
      {hint && <p className="text-xs text-gray-400 dark:text-gray-500">{hint}</p>}
    </div>
  );
}

interface ReportViewProps {
  report: Report;
  theme: Theme;
  onToggleTheme: () => void;
  onAnalyze: (request: AnalyzeRequest) => void;
  /** Returns to the landing search page without losing browser history. */
  onReset: () => void;
  /** True while a re-analysis request (from this view) is in flight. */
  loading: boolean;
  /** Set when a re-analysis request failed; the previously loaded report stays visible. */
  error: ApiError | null;
  onDismissError: () => void;
}

export function ReportView({
  report,
  theme,
  onToggleTheme,
  onAnalyze,
  onReset,
  loading,
  error,
  onDismissError,
}: ReportViewProps) {
  const [reInput, setReInput] = useState("");
  const [platform, setPlatform] = useState<PlatformFilter>(report.platform);
  const { score, meta } = report;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    const trimmed = reInput.trim();
    if (!trimmed) return;
    onAnalyze(meta.mode === "local-path" ? { path: trimmed, platform } : { source: trimmed, platform });
  }

  const sha = shortSha(meta.resolved_sha);
  const scanLabel = meta.mode === "online-scan" ? "online scan, no clone" : "local path scan";

  return (
    <div>
      {/* Sticky compact header */}
      <header className="sticky top-0 z-10 border-b border-gray-200 bg-white/85 backdrop-blur dark:border-night-border dark:bg-night-page/85">
        {/* Indeterminate progress bar while a re-analysis is in flight. */}
        {loading && (
          <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-gray-100 dark:bg-night-border" aria-hidden="true">
            <div className="loading-bar h-full w-1/3 bg-brand" />
          </div>
        )}
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
          <button
            type="button"
            onClick={onReset}
            className="focus-ring flex items-center gap-2 rounded-md"
            aria-label="Back to AgentCompass home"
          >
            <Logo size={28} markOnly />
            <span className="text-sm font-bold">
              <span className="text-gray-900 dark:text-white">Agent</span>
              <span className="text-gradient">Compass</span>
            </span>
          </button>
          <span className="hidden text-gray-300 dark:text-gray-600 sm:inline" aria-hidden="true">
            /
          </span>
          <span className="font-mono text-sm text-gray-700 dark:text-night-text">
            {meta.source}
            {meta.ref ? `@${meta.ref}` : ""}
          </span>
          <form onSubmit={submit} className="ml-auto flex flex-wrap items-center gap-2">
            <PlatformToggle value={platform} onChange={setPlatform} disabled={loading} />
            <label htmlFor="reanalyze-input" className="sr-only">
              Analyze another repository
            </label>
            <input
              id="reanalyze-input"
              type="text"
              value={reInput}
              onChange={(event) => setReInput(event.target.value)}
              placeholder={meta.mode === "local-path" ? "another/path" : "owner/repo"}
              autoComplete="off"
              spellCheck={false}
              disabled={loading}
              className="focus-ring h-9 w-40 rounded-lg border border-gray-300 bg-white px-3 text-sm text-gray-900 placeholder:text-gray-400 disabled:cursor-not-allowed disabled:opacity-60 dark:border-night-border dark:bg-night-card dark:text-night-text sm:w-56"
            />
            <button
              type="submit"
              disabled={loading}
              className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading && <Spinner />}
              {loading ? "Analyzing\u2026" : "Analyze"}
            </button>
          </form>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-4 py-8">
        {error && (
          <ErrorState error={error} onDismiss={onDismissError} />
        )}

        {report.platform !== "all" && (
          <p className="text-center text-xs font-medium text-brand">
            Scored for {PLATFORM_LABEL[report.platform]} only &mdash; pillars and findings below exclude
            rules that only apply to the other platform.
          </p>
        )}

        {/* Summary row */}
        <div className="grid gap-4 md:grid-cols-[auto_1fr]">
          <div className="card flex items-center justify-center p-6">
            <ScoreRing score={score} />
          </div>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-2">
            {report.platform !== "claude" && (
              <StatCard label="Copilot score" value={formatScore(score.copilot)} hint="platform score / 100" />
            )}
            {report.platform !== "copilot" && (
              <StatCard label="Claude score" value={formatScore(score.claude)} hint="platform score / 100" />
            )}
            {report.platform === "all" && (
              <StatCard label="Parity delta" value={formatDelta(score.parity_delta)} hint="Copilot vs Claude gap" />
            )}
            <StatCard
              label="Findings"
              value={String(report.findings.length)}
              hint={score.has_error_finding ? "includes errors" : "no errors"}
            />
          </div>
        </div>

        {/* Meta line */}
        <p className="text-center text-xs text-gray-500 dark:text-night-muted">
          {meta.listed_files.toLocaleString()} files listed &middot;{" "}
          {meta.fetched_files.toLocaleString()} fetched &middot; {meta.duration_ms.toLocaleString()}{" "}
          ms &middot; {scanLabel}
          {sha ? (
            <>
              {" "}
              &middot; <span className="font-mono">{sha}</span>
            </>
          ) : null}
        </p>

        <PillarTable pillars={report.pillars} />
        <TopFixes plan={report.remediation_plan} />
        <FindingsTable findings={report.findings} />
        <WaiversPanel waivers={report.waivers} expiredWaivers={report.expired_waivers} />

        <footer className="pt-4 text-center text-xs text-gray-400 dark:text-gray-500">
          AgentCompass {report.tool_version} &middot; ruleset {report.ruleset_version} &middot;
          schema {report.schema_version}
        </footer>
      </main>
    </div>
  );
}

export default ReportView;
