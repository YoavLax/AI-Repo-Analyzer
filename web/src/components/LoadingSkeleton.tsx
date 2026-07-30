/** Skeleton dashboard shown while the analysis request is in flight. */
export function LoadingSkeleton() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-10" aria-busy="true">
      <p
        role="status"
        className="mb-8 text-center text-sm text-gray-600 dark:text-night-muted"
      >
        Scanning via the GitHub API &mdash; fetching only AI-artifact files, no clone.
      </p>

      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        {/* Score ring placeholder */}
        <div className="card flex items-center justify-center p-6">
          <div className="skeleton h-36 w-36 rounded-full" />
        </div>
        {/* Stat cards */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card flex flex-col justify-center gap-3 p-5">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton h-8 w-14" />
            </div>
          ))}
        </div>
      </div>

      {/* Pillar table placeholder */}
      <div className="card mt-4 p-6">
        <div className="skeleton mb-5 h-4 w-24" />
        <div className="space-y-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="skeleton h-3 w-28" />
              <div className="skeleton h-2.5 flex-1" />
              <div className="skeleton h-3 w-10" />
            </div>
          ))}
        </div>
      </div>

      {/* Findings placeholder */}
      <div className="card mt-4 p-6">
        <div className="skeleton mb-5 h-4 w-32" />
        <div className="space-y-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton h-9 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

export default LoadingSkeleton;
