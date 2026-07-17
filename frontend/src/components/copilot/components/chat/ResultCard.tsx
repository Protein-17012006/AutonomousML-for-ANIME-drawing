// Final agent message: session stats + artifacts + board handoff + exports.
import type { ResultEvent } from "../../types";
import { Button } from "@/components/ui/button";

/* cadence_fps → "shoot on Ns" label; falls back to a plain "Nfps" for an unrecognized rate */
function cadenceLabel(cadenceFps?: number): string {
  if (cadenceFps === 24) return "on-1s";
  if (cadenceFps === 12) return "on-2s";
  if (cadenceFps === 8) return "on-3s";
  return cadenceFps != null ? `${cadenceFps}fps` : "";
}

export function ResultCard({ result, keyUrls, onOpenBoard, onExport }: {
  result: ResultEvent;
  keyUrls: string[];
  onOpenBoard: () => void;
  onExport: (result: ResultEvent) => void;
}) {
  const art = result.artifacts;
  const samp = result.sampling;
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
      {samp?.output_fps != null && (
        // sampling badge — what cadence × smoothness the box actually delivered this run
        // (cadence/smoothness echo the request; the server is the source of truth here).
        <p className="result-sampling" title="cadence × smoothness → delivered playback rate">
          {samp.smoothness != null && <>×{samp.smoothness} · </>}
          {samp.cadence_fps != null && <>{cadenceLabel(samp.cadence_fps)} → </>}
          {samp.output_fps}fps
          {samp.duration != null && <> · {samp.duration}s</>}
        </p>
      )}
      {art && (
        <p className="result-links">
          <a href={art.montage} target="_blank" rel="noreferrer">montage</a>
          {" · "}<a href={art.video} target="_blank" rel="noreferrer">reconstructed cut</a>
          {art.report && <>{" · "}<a href={art.report} target="_blank" rel="noreferrer">report</a></>}
        </p>
      )}
      <div className="result-actions">
        <Button type="button" className="border-ao bg-ao font-mono text-[12.5px] font-semibold tracking-[0.02em] text-on-ao hover:bg-ao/85" onClick={onOpenBoard}>Open review board</Button>
        <Button type="button" variant="outline" className="font-mono text-[12.5px] tracking-[0.02em]" onClick={() => onExport(result)}>Export bundle ⤓</Button>
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
