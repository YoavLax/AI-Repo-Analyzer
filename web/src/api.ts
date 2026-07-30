/**
 * Typed client for the CodeCompass API.
 *
 * The DTOs mirror the canonical report JSON produced by
 * `src/airx/report/json.py::to_json_dict` (schema 0.2.0) plus the `meta`
 * block added by `airx_server.service`. Keep them in sync with the backend —
 * `tsc --noEmit` is the schema-drift gate in CI.
 */

export type SeverityLevel = "error" | "warning" | "info";
export type EffortLevel = "mechanical" | "additive" | "authoring" | "organizational";
export type GradeLetter = "A" | "B" | "C" | "D" | "E" | "F";

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
  | { source: string; ref?: string | null }
  | { path: string };

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
    throw new ApiError(0, "Could not reach the CodeCompass server.");
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

/** GET /api/version — {version, local_mode}. */
export function version(): Promise<VersionInfo> {
  return request<VersionInfo>("/api/version");
}
