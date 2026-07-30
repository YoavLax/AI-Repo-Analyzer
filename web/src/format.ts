import type { EffortLevel, GradeLetter, SeverityLevel } from "./api";

/** Grade → accent color (WCAG-checked against white/night cards). */
export const GRADE_COLORS: Record<GradeLetter, string> = {
  A: "#12B76A",
  B: "#66C61C",
  C: "#EAAA08",
  D: "#F79009",
  E: "#F04438",
  F: "#F04438",
};

export function gradeColor(grade: string): string {
  return GRADE_COLORS[grade as GradeLetter] ?? "#667085";
}

export const SEVERITY_LABELS: Record<SeverityLevel, string> = {
  error: "Error",
  warning: "Warning",
  info: "Info",
};

/** Effort class → muted chip classes (light + dark). */
export const EFFORT_STYLES: Record<EffortLevel, string> = {
  mechanical: "bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300",
  additive: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  authoring: "bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  organizational: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
};

export function effortStyle(effort: string): string {
  return (
    EFFORT_STYLES[effort as EffortLevel] ??
    "bg-gray-100 text-gray-700 dark:bg-gray-500/10 dark:text-gray-300"
  );
}

/** Middle-truncate long repo paths: "src/…/deeply/nested/file.md". */
export function truncateMiddle(text: string, max = 48): string {
  if (text.length <= max) return text;
  const keep = max - 1;
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`;
}

export function shortSha(sha: string | null): string | null {
  return sha ? sha.slice(0, 7) : null;
}

export function formatPoints(gain: number): string {
  const rounded = Math.round(gain * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export function formatScore(value: number | null): string {
  if (value === null) return "—";
  return String(Math.round(value * 10) / 10);
}

export function formatDelta(value: number | null): string {
  if (value === null) return "—";
  const rounded = Math.round(value * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return rounded > 0 ? `+${text}` : text;
}
