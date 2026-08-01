import { useCallback, useEffect, useState } from "react";
import { analyze, ApiError, version, type AnalyzeRequest, type Report } from "./api";
import ErrorState from "./components/ErrorState";
import LoadingSkeleton from "./components/LoadingSkeleton";
import ReportView from "./components/ReportView";
import SearchHero from "./components/SearchHero";
import ThemeToggle from "./components/ThemeToggle";
import { useTheme } from "./theme";

type AppState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "report"; report: Report }
  | { phase: "error"; error: ApiError };

export function App() {
  const { theme, toggle } = useTheme();
  const [state, setState] = useState<AppState>({ phase: "idle" });
  const [localMode, setLocalMode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    version()
      .then((info) => {
        if (!cancelled) setLocalMode(info.local_mode);
      })
      .catch(() => {
        /* hero still works without version info; local tab stays hidden */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runAnalysis = useCallback((request: AnalyzeRequest) => {
    setState({ phase: "loading" });
    window.scrollTo({ top: 0 });
    analyze(request)
      .then((report) => setState({ phase: "report", report }))
      .catch((error: unknown) => {
        const apiError =
          error instanceof ApiError ? error : new ApiError(0, "Unexpected client error.");
        setState({ phase: "error", error: apiError });
      });
  }, []);

  if (state.phase === "report") {
    return (
      <ReportView
        report={state.report}
        theme={theme}
        onToggleTheme={toggle}
        onAnalyze={runAnalysis}
      />
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col">
      <div className="absolute right-4 top-4">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>

      {state.phase === "loading" ? (
        <LoadingSkeleton />
      ) : (
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-4 py-16">
          <SearchHero localMode={localMode} onAnalyze={runAnalysis} />
          {state.phase === "error" && <ErrorState error={state.error} />}
        </div>
      )}
    </div>
  );
}

export default App;
