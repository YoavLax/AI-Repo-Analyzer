/**
 * Typed client for the AgentCompass API.
 *
 * The DTOs mirror the canonical report JSON produced by
 * `src/airx/report/json.py::to_json_dict` (schema 0.2.0) plus the `meta`
 * block added by `airx_server.service`. Keep them in sync with the backend —
 * `tsc --noEmit` is the schema-drift gate in CI.
 */

export type SeverityLevel = "error" | "warning" | "info";
export type EffortLevel = "mechanical" | "additive" | "authoring" | "organizational";
export type GradeLetter = "A" | "B" | "C" | "D" | "E" | "F";
/** Restricts scoring to one agent harness's rules; "all" scores both (default). */
export type PlatformFilter = "all" | "copilot" | "claude";

export interface Finding {
  rule_id: string;
  pillar: string;
  severity: SeverityLevel;
  source: string;
  weight: number;
  path: string | null;
  line: number | null;
  message: string;
  context: string | null;
  doc_url: string | null;
  why: string | null;
  fix: string | null;
  effort: EffortLevel;
}

export interface PillarScore {
  id: string;
  weight: number;
  /** 0..1, null when the pillar has no registered rules ("not scored"). */
  score: number | null;
  presence_ratio: number | null;
  quality_ratio: number | null;
  rule_count: number;
}

export interface Artifact {
  path: string;
  kind: string;
  platform: string;
  parse_error: string | null;
}

export interface RepoFacts {
  languages: [string, number][];
  package_scripts: string[];
  makefile_targets: string[];
  test_evidence: boolean;
  lint_evidence: boolean;
  build_evidence: boolean;
  ci_workflows: string[];
  has_env_example: boolean;
  has_devcontainer: boolean;
  has_setup_script: boolean;
  version_pins: string[];
}

export interface Inventory {
  skills_found: string[];
  skill_parse_errors: string[];
  copilot_instructions: string | null;
  agents_md: string[];
  claude_md: string | null;
  artifacts: Artifact[];
  repo_facts: RepoFacts | null;
}

export interface Score {
  /** 0..100 */
  overall: number;
  grade: GradeLetter;
  raw_grade: GradeLetter;
  grade_capped: boolean;
  has_error_finding: boolean;
  copilot: number | null;
  claude: number | null;
  parity_delta: number | null;
  /** 1-5, derived from `grade` (config.MATURITY_LEVELS). */
  maturity_level: number;
  /** Functional | Documented | Standardized | Optimized | Autonomous */
  maturity_label: string;
}

export interface Waiver {
  rule: string;
  reason: string;
  expires: string | null;
  approved_by: string | null;
}

export interface RemediationEntry {
  rank: number;
  rule_id: string;
  score_gain: number;
  effort: EffortLevel;
  action: string;
  paths: string[];
}

export interface Meta {
  source: string;
  ref: string | null;
  resolved_sha: string | null;
  listed_files: number;
  fetched_files: number;
  fetched_bytes: number;
  duration_ms: number;
  mode: "online-scan" | "local-path";
}

export interface Report {
  schema_version: string;
  tool_version: string;
  ruleset_version: string;
  profile: string;
  /** The `--platform`/API filter this report was scored with ("all" when unscoped). */
  platform: PlatformFilter;
  target: { root: string };
  score: Score;
  pillars: PillarScore[];
  inventory: Inventory;
  findings: Finding[];
  waivers: Waiver[];
  expired_waivers: Waiver[];
  ignored_rules: string[];
  remediation_plan: RemediationEntry[];
  caveats: string[];
  meta: Meta;
}

export interface VersionInfo {
  version: string;
  local_mode: boolean;
}

export type AnalyzeRequest =
  | ({ source: string; ref?: string | null } & { platform?: PlatformFilter })
  | ({ path: string } & { platform?: PlatformFilter });

/** Server error body: {"error": {"code", "message"}}. */
interface ErrorBody {
  error: { code: number; message: string };
}

export class ApiError extends Error {
  /** HTTP status; 0 when the server was unreachable. */
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const err = (value as Record<string, unknown>)["error"];
  if (typeof err !== "object" || err === null) return false;
  const { code, message } = err as Record<string, unknown>;
  return typeof code === "number" && typeof message === "string";
}

async function throwApiError(response: Response): Promise<never> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error body (proxy, crash page) — fall through */
  }
  if (isErrorBody(body)) {
    throw new ApiError(response.status, body.error.message);
  }
  throw new ApiError(response.status, `Unexpected server error (HTTP ${response.status}).`);
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch {
    throw new ApiError(0, "Could not reach the AgentCompass server.");
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as T;
}

/** POST /api/analyze — returns the canonical report plus `meta`. */
export function analyze(body: AnalyzeRequest): Promise<Report> {
  return request<Report>("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Ingest phases reported by `/api/analyze/stream`, in the order they occur.
 * Mirrors `airx.ingest` (`PHASE_*`) plus the service's `scoring`.
 */
export type AnalysisPhase = "resolving" | "listing" | "fetching" | "linked" | "scoring";

/** `total` is 0 while a phase's work is not yet countable. */
export interface AnalysisProgress {
  phase: AnalysisPhase;
  done: number;
  total: number;
}

type StreamEvent =
  | ({ type: "progress" } & AnalysisProgress)
  | { type: "result"; report: Report }
  | { type: "error"; error: { code: number; message: string } };

/** Applies one NDJSON line; returns the report if this was the terminal one. */
function applyStreamLine(line: string, onProgress: (p: AnalysisProgress) => void): Report | null {
  let event: StreamEvent;
  try {
    event = JSON.parse(line) as StreamEvent;
  } catch {
    // A proxy injecting a non-JSON line would otherwise abort a run that the
    // server may well have completed; skip it and keep reading for the result.
    return null;
  }
  if (event.type === "progress") {
    onProgress({ phase: event.phase, done: event.done, total: event.total });
    return null;
  }
  if (event.type === "error") {
    throw new ApiError(event.error.code, event.error.message);
  }
  return event.report;
}

/**
 * POST /api/analyze/stream — the same report as `analyze`, with real progress.
 *
 * `onProgress` is driven by counts the server actually measured (files listed,
 * files fetched), not by elapsed time, so the caller can render a bar that
 * tracks the work instead of guessing at it.
 */
export async function analyzeStreaming(
  body: AnalyzeRequest,
  onProgress: (progress: AnalysisProgress) => void,
): Promise<Report> {
  let response: Response;
  try {
    response = await fetch("/api/analyze/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Could not reach the AgentCompass server.");
  }
  if (!response.ok) {
    await throwApiError(response);
  }

  let report: Report | null = null;
  const consume = (line: string) => {
    const trimmed = line.trim();
    if (trimmed) report = applyStreamLine(trimmed, onProgress) ?? report;
  };

  if (!response.body) {
    // No ReadableStream (older browser, or a proxy that buffered the whole
    // body). The analysis has already run — parse what arrived rather than
    // re-requesting, which would make the server do all of it a second time.
    (await response.text()).split("\n").forEach(consume);
  } else {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline >= 0) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
    }
    consume(buffer + decoder.decode());
  }

  if (report === null) {
    throw new ApiError(502, "The analysis ended without returning a report.");
  }
  return report;
}

/** GET /api/version — {version, local_mode}. */
export function version(): Promise<VersionInfo> {
  return request<VersionInfo>("/api/version");
}
