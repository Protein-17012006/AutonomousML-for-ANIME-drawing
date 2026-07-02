// Final agent message: session stats + artifacts + board handoff + exports.
import type { ResultEvent } from "../../types";

export function ResultCard({ result, keyUrls, onOpenBoard, onExport }: {
  result: ResultEvent;
  keyUrls: string[];
  onOpenBoard: () => void;
  onExport: (result: ResultEvent) => void;
}) {
  const art = result.artifacts;
  // export-the-flagged-keys affordance (design §0.1): the artist fixes in their own
  // tool, so hand them the endpoint keys of every flagged pair.
  const flaggedKeys = Array.from(
    new Set(result.flagged.flatMap((i) => [i, i + 1])),
  ).filter((i) => keyUrls[i]);
  return (
    <div className="bubble agent result-card">
      <div className="bubble-label">Session done</div>
      <p className="result-stats">
        ✓ {result.n_autopass} auto-pass · 🔧 {result.n_corrected} corrected ·
        ⚑ {result.flagged.length} flagged · 🤔 {result.abstained.length} unsure ·
        🔑 {result.keys_requested_total} keys requested
      </p>
      {art && (
        <p className="result-links">
          <a href={art.montage} target="_blank" rel="noreferrer">montage</a>
          {" · "}<a href={art.video} target="_blank" rel="noreferrer">reconstructed cut</a>
          {art.report && <>{" · "}<a href={art.report} target="_blank" rel="noreferrer">report</a></>}
        </p>
      )}
      <div className="result-actions">
        <button type="button" className="btn btn-primary" onClick={onOpenBoard}>Open review board</button>
        <button type="button" className="btn btn-ghost" onClick={() => onExport(result)}>Export bundle ⤓</button>
      </div>
      {flaggedKeys.length > 0 && (
        <p className="result-flagged-keys">
          flagged-pair keys:{" "}
          {flaggedKeys.map((i) => (
            <a key={i} href={keyUrls[i]} download={`key_${i}.png`}>key {i}</a>
          ))}
        </p>
      )}
    </div>
  );
}
