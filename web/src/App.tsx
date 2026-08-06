import { useCallback, useEffect, useRef, useState } from "react";
import {
  analyzeStreaming,
  ApiError,
  version,
  type AnalysisProgress,
  type AnalyzeRequest,
  type PlatformFilter,
  type Report,
} from "./api";
import AuraBackground from "./components/AuraBackground";
import CoreTeam from "./components/CoreTeam";
import ErrorState from "./components/ErrorState";
import LoadingSkeleton from "./components/LoadingSkeleton";
import ReportView from "./components/ReportView";
import SearchHero from "./components/SearchHero";
import ThemeToggle from "./components/ThemeToggle";
import { useTheme } from "./theme";

type Status = "idle" | "loading" | "error";

interface AppState {
  status: Status;
  /** Last successful report, kept around while a re-analysis is loading or fails. */
  report: Report | null;
  error: ApiError | null;
}

const INITIAL_STATE: AppState = { status: "idle", report: null, error: null };

function isPlatformFilter(value: string | null): value is PlatformFilter {
  return value === "copilot" || value === "claude" || value === "all";
}

/** Reads `?repo=owner/name[&ref=...]` or `?path=...`, plus an optional `?platform=`, from the current URL. */
function requestFromLocation(): AnalyzeRequest | null {
  const params = new URLSearchParams(window.location.search);
  const platformParam = params.get("platform");
  const platform: PlatformFilter | undefined = isPlatformFilter(platformParam) ? platformParam : undefined;
  const path = params.get("path");
  if (path) return { path, platform };
  const repo = params.get("repo");
  if (repo) return { source: repo, ref: params.get("ref"), platform };
  return null;
}

/** Builds the shareable `?repo=` / `?path=` URL for a request, preserving the current path. */
function urlForRequest(request: AnalyzeRequest): string {
  const params = new URLSearchParams();
  if ("path" in request) {
    params.set("path", request.path);
  } else {
    params.set("repo", request.source);
    if (request.ref) params.set("ref", request.ref);
  }
  if (request.platform && request.platform !== "all") params.set("platform", request.platform);
  return `${window.location.pathname}?${params.toString()}`;
}

export function App() {
  const { theme, toggle } = useTheme();
  const [state, setState] = useState<AppState>(INITIAL_STATE);
  const [localMode, setLocalMode] = useState(false);
  // Server-reported progress for the in-flight analysis; null until its first
  // event arrives, which is what tells the loading view to stay indeterminate
  // rather than draw a bar at a number it has not been told yet.
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  // Guards against a stale in-flight request clobbering state after a newer one starts.
  const requestId = useRef(0);

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

  const runAnalysis = useCallback((request: AnalyzeRequest, options?: { fromHistory?: boolean }) => {
    const id = ++requestId.current;
    setState((prev) => ({ status: "loading", report: prev.report, error: null }));
    setProgress(null);
    window.scrollTo({ top: 0 });
    if (!options?.fromHistory) {
      const url = urlForRequest(request);
      if (url !== `${window.location.pathname}${window.location.search}`) {
        window.history.pushState({}, "", url);
      }
    }
    analyzeStreaming(request, (update) => {
      // Drop updates from a superseded request, or a slow earlier stream would
      // drive the bar for the run the user is actually waiting on.
      if (id === requestId.current) setProgress(update);
    })
      .then((report) => {
        if (id !== requestId.current) return;
        setState({ status: "idle", report, error: null });
      })
      .catch((error: unknown) => {
        if (id !== requestId.current) return;
        const apiError =
          error instanceof ApiError ? error : new ApiError(0, "Unexpected client error.");
        setState((prev) => ({ status: "error", report: prev.report, error: apiError }));
      });
  }, []);

  // Deep-link support: analyze whatever `?repo=`/`?path=` is in the URL on first load,
  // and again whenever the user navigates with the browser's back/forward buttons.
  useEffect(() => {
    const initial = requestFromLocation();
    if (initial) runAnalysis(initial, { fromHistory: true });

    function onPopState() {
      const request = requestFromLocation();
      if (request) {
        runAnalysis(request, { fromHistory: true });
      } else {
        requestId.current += 1;
        setState(INITIAL_STATE);
      }
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goHome = useCallback(() => {
    requestId.current += 1;
    window.history.pushState({}, "", window.location.pathname);
    setState(INITIAL_STATE);
  }, []);

  const dismissError = useCallback(() => {
    setState((prev) => ({ ...prev, status: "idle", error: null }));
  }, []);

  if (state.report) {
    return (
      <ReportView
        report={state.report}
        theme={theme}
        onToggleTheme={toggle}
        onAnalyze={runAnalysis}
        onReset={goHome}
        loading={state.status === "loading"}
        error={state.status === "error" ? state.error : null}
        onDismissError={dismissError}
      />
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      {state.status !== "loading" && <AuraBackground />}
      <div className="absolute right-4 top-4">
        <ThemeToggle theme={theme} onToggle={toggle} />
      </div>

      {state.status === "loading" ? (
        <LoadingSkeleton progress={progress} />
      ) : (
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-4 py-16">
          <SearchHero localMode={localMode} onAnalyze={runAnalysis} />
          {state.status === "error" && state.error && <ErrorState error={state.error} />}
          <CoreTeam />
        </div>
      )}
    </div>
  );
}

export default App;
