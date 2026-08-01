import type { Waiver } from "../api";

interface WaiversPanelProps {
  waivers: Waiver[];
  expiredWaivers: Waiver[];
}

function WaiverRow({ waiver, expired }: { waiver: Waiver; expired: boolean }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5">
      <span className="font-mono text-[13px] text-primary-700 dark:text-primary-400">
        {waiver.rule}
      </span>
      {expired && (
        <span className="inline-flex items-center rounded-full bg-danger-50 px-2 py-0.5 text-xs font-medium text-danger-700 dark:bg-red-500/10 dark:text-red-300">
          expired
        </span>
      )}
      <span className="text-sm text-gray-600 dark:text-night-muted">{waiver.reason}</span>
      <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">
        {waiver.expires ? `expires ${waiver.expires}` : "no expiry"}
        {waiver.approved_by ? ` · approved by ${waiver.approved_by}` : ""}
      </span>
    </li>
  );
}

/** Rendered only when there is at least one active or expired waiver. */
export function WaiversPanel({ waivers, expiredWaivers }: WaiversPanelProps) {
  if (waivers.length === 0 && expiredWaivers.length === 0) return null;

  return (
    <section className="card p-6" aria-label="Waivers">
      <h2 className="mb-3 text-base font-semibold">Waivers</h2>
      <ul className="divide-y divide-gray-100 dark:divide-night-border">
        {waivers.map((waiver) => (
          <WaiverRow key={`active-${waiver.rule}`} waiver={waiver} expired={false} />
        ))}
        {expiredWaivers.map((waiver) => (
          <WaiverRow key={`expired-${waiver.rule}`} waiver={waiver} expired />
        ))}
      </ul>
    </section>
  );
}

export default WaiversPanel;
