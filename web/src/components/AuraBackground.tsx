/**
 * Ambient decorative backdrop for the landing hero: soft, slow-drifting
 * brand-gradient blobs over a faint dot grid. Purely decorative — absolutely
 * positioned, non-interactive (aria-hidden), and fully disabled under
 * prefers-reduced-motion (see the `.aura-blob` rule in styles.css). This is
 * the app's one signature background treatment; avoid stacking it with
 * other effects elsewhere.
 */
export function AuraBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0 bg-dot-grid text-gray-300 dark:text-night-border" />
      <div className="aura-blob absolute -left-24 -top-32 h-[28rem] w-[28rem] rounded-full bg-primary-400/25 blur-3xl dark:bg-primary-500/15" />
      <div className="aura-blob aura-blob-delay-1 absolute -right-32 top-1/3 h-[26rem] w-[26rem] rounded-full bg-brandblue/20 blur-3xl dark:bg-brandblue/10" />
      <div className="aura-blob aura-blob-delay-2 absolute -bottom-40 left-1/4 h-96 w-96 rounded-full bg-primary-300/20 blur-3xl dark:bg-primary-700/15" />
    </div>
  );
}

export default AuraBackground;
