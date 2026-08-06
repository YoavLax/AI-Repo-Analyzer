import type { PlatformFilter } from "../api";

interface PlatformToggleProps {
  value: PlatformFilter;
  onChange: (value: PlatformFilter) => void;
  disabled?: boolean;
  className?: string;
}

const OPTIONS: { value: PlatformFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "copilot", label: "Copilot" },
  { value: "claude", label: "Claude Code" },
];

/** Restricts scoring/findings to one agent harness, so results for a harness
 * a person doesn't use don't get mixed into the report. */
export function PlatformToggle({ value, onChange, disabled, className }: PlatformToggleProps) {
  return (
    <div
      role="group"
      aria-label="Score for platform"
      className={`inline-flex rounded-lg border border-gray-200 bg-white p-1 dark:border-night-border dark:bg-night-card ${className ?? ""}`}
    >
      {OPTIONS.map((option) => {
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`focus-ring whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
              active
                ? "bg-gray-100 text-gray-900 dark:bg-night-border dark:text-night-text"
                : "text-gray-500 hover:text-gray-700 dark:text-night-muted dark:hover:text-night-text"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default PlatformToggle;
