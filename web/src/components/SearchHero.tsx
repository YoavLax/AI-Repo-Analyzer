import { FormEvent, useState } from "react";
import type { AnalyzeRequest, PlatformFilter } from "../api";
import Logo from "./Logo";
import PlatformToggle from "./PlatformToggle";

const EXAMPLES = ["vercel/next.js", "facebook/react", "YoavLax/agent-compass"];

const TRUST_STATS: Array<[string, string]> = [
  ["104", "deterministic rules"],
  ["0", "clone required"],
  ["No", "signup"],
];

type InputMode = "github" | "local";

interface SearchHeroProps {
  localMode: boolean;
  onAnalyze: (request: AnalyzeRequest) => void;
}

export function SearchHero({ localMode, onAnalyze }: SearchHeroProps) {
  const [mode, setMode] = useState<InputMode>("github");
  const [value, setValue] = useState("");
  const [platform, setPlatform] = useState<PlatformFilter>("all");

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onAnalyze(mode === "local" ? { path: trimmed, platform } : { source: trimmed, platform });
  }

  const githubActive = mode === "github";

  return (
    <section className="flex flex-col items-center gap-8 text-center">
      <Logo size={64} withTagline />
      <div className="flex flex-col items-center gap-4">
        <h1 className="max-w-2xl text-3xl font-bold tracking-tight text-gray-900 dark:text-night-text sm:text-4xl">
          Is your repo ready for <span className="text-gradient">AI agents</span>?
        </h1>
        <p className="max-w-xl text-base text-gray-600 dark:text-night-muted">
          Score any public GitHub repo&rsquo;s readiness for Copilot &amp; Claude Code &mdash;
          deterministic checks, concrete fixes, no clone, no signup.
        </p>
        <dl className="flex flex-wrap items-center justify-center gap-2">
          {TRUST_STATS.map(([value, label]) => (
            <div
              key={label}
              className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white/70 px-3 py-1 text-xs dark:border-night-border dark:bg-night-card/70"
            >
              <dt className="font-semibold text-primary-700 dark:text-primary-400">{value}</dt>
              <dd className="text-gray-500 dark:text-night-muted">{label}</dd>
            </div>
          ))}
        </dl>
      </div>

      {localMode && (
        <div
          role="group"
          aria-label="Analysis source"
          className="inline-flex rounded-lg border border-gray-200 bg-white p-1 dark:border-night-border dark:bg-night-card"
        >
          <button
            type="button"
            aria-pressed={githubActive}
            onClick={() => setMode("github")}
            className={`focus-ring rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              githubActive
                ? "bg-gray-100 text-gray-900 dark:bg-night-border dark:text-night-text"
                : "text-gray-500 hover:text-gray-700 dark:text-night-muted dark:hover:text-night-text"
            }`}
          >
            GitHub URL
          </button>
          <button
            type="button"
            aria-pressed={!githubActive}
            onClick={() => setMode("local")}
            className={`focus-ring rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              !githubActive
                ? "bg-gray-100 text-gray-900 dark:bg-night-border dark:text-night-text"
                : "text-gray-500 hover:text-gray-700 dark:text-night-muted dark:hover:text-night-text"
            }`}
          >
            Local path
          </button>
        </div>
      )}

      <PlatformToggle value={platform} onChange={setPlatform} />

    <form onSubmit={submit} className="flex w-full max-w-xl flex-col gap-3">
        <div className="flex w-full gap-2">
          <label htmlFor="repo-input" className="sr-only">
            {githubActive ? "GitHub repository URL or owner/repo" : "Repository path"}
          </label>
          <input
            id="repo-input"
            type="text"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={
              githubActive ? "github.com/owner/repo or owner/repo" : "my-team/service-repo"
            }
            autoComplete="off"
            spellCheck={false}
            className="focus-ring h-11 w-full rounded-lg border border-gray-300 bg-white px-3.5 text-base text-gray-900 placeholder:text-gray-400 dark:border-night-border dark:bg-night-card dark:text-night-text dark:placeholder:text-gray-500"
          />
          <button
            type="submit"
            className="focus-ring h-11 shrink-0 rounded-lg bg-brand px-5 text-sm font-semibold text-white shadow-card transition-opacity hover:bg-brand-hover"
          >
            Analyze
          </button>
        </div>
        {!githubActive && (
          <p className="text-left text-xs text-gray-500 dark:text-night-muted">
            Path relative to the server&rsquo;s configured repos root
            (<code className="font-mono">LOCAL_REPOS_ROOT</code>).
          </p>
        )}
      </form>

      {githubActive && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          <span className="text-xs text-gray-500 dark:text-night-muted">Try:</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setValue(example)}
              className="focus-ring rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 transition-colors hover:border-primary-300 hover:text-primary-700 dark:border-night-border dark:bg-night-card dark:text-night-muted dark:hover:border-primary-600 dark:hover:text-primary-400"
            >
              {example}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export default SearchHero;
