import type { ApiError } from "../api";

interface ErrorCopy {
  title: string;
  body: string;
  note?: string;
}

function copyFor(error: ApiError): ErrorCopy {
  switch (error.status) {
    case 400:
      return {
        title: "That input didn't look right",
        body: error.message,
      };
    case 404:
      return {
        title: "Repository not found or private",
        body: error.message,
        note: "Private repositories can be analyzed on a self-hosted AgentCompass with a GITHUB_TOKEN, or via local-path mode.",
      };
    case 413:
      return {
        title: "Repository too large for an online scan",
        body: error.message,
        note: "Self-host AgentCompass next to a local clone and use local-path mode for very large repositories.",
      };
    case 422:
      return {
        title: "Local mode is disabled on this server",
        body: error.message,
      };
    case 429:
      return {
        title: "GitHub rate limit reached",
        body: error.message,
        note: "Set a GITHUB_TOKEN on the server to raise the GitHub API limit from 60 to 5,000 requests per hour.",
      };
    case 0:
      return {
        title: "Can't reach the server",
        body: error.message,
      };
    default:
      return {
        title: "Something went wrong",
        body: error.message,
      };
  }
}

interface ErrorStateProps {
  error: ApiError;
  /** When provided, renders a close button so the banner can be dismissed without losing context. */
  onDismiss?: () => void;
}

export function ErrorState({ error, onDismiss }: ErrorStateProps) {
  const copy = copyFor(error);
  return (
    <div
      role="alert"
      className="card mx-auto w-full max-w-xl border-danger-500/20 p-6 text-left"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger-50 dark:bg-red-500/10">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#F04438" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v4.5M12 16h.01" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{copy.title}</h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-night-muted">{copy.body}</p>
          {copy.note && (
            <p className="mt-3 rounded-lg bg-gray-50 p-3 text-xs text-gray-500 dark:bg-night-page dark:text-night-muted">
              {copy.note}
            </p>
          )}
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss error"
            className="focus-ring -m-1 shrink-0 rounded-md p-1 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-night-text"
          >
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="m5 5 10 10M15 5 5 15" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

export default ErrorState;
