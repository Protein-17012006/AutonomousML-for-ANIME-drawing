// self-drawing run loader (a cel + peg-bar drawing themselves). Extracted from CopilotApp.tsx.
export function RunLoader() {
  return (
    <div className="runloader" role="status" aria-live="polite">
      <svg className="runloader-svg" viewBox="0 0 120 80" fill="none" aria-hidden="true">
        <rect className="dl dl-frame" pathLength={1} x="8" y="8" width="104" height="58" rx="4" />
        <circle className="dl dl-peg" pathLength={1} cx="46" cy="72" r="2.5" />
        <circle className="dl dl-peg" pathLength={1} cx="60" cy="72" r="2.5" />
        <circle className="dl dl-peg" pathLength={1} cx="74" cy="72" r="2.5" />
        <path className="dl dl-stroke" pathLength={1} d="M22 50 C 42 22, 78 22, 98 46" />
      </svg>
      <p className="runloader-cap">co-pilot is drawing the in-betweens…</p>
    </div>
  );
}
