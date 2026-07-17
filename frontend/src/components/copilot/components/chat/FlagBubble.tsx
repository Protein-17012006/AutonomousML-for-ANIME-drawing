// Flagged-pair bubble: triptych + red region-box overlay (fallback) + QA facts + director trace.
// Prefers server-burned annotated frame (annotated_url) when available; falls back to raw mid + CSS overlay.
// The overlay uses the EXISTING server-computed fractional box (service/app.py region_box)
// — grid-coarse (3×3 VLM region), honestly not a pixel mask (design §0.5).
import type { Explanation, PairEvent } from "../../types";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { errTypeLabel, qaLabel } from "../../labels";

/* eslint-disable @next/next/no-img-element -- session artifacts and object URLs are dynamic. */

function puLine(p: PairEvent): string {
  const bits: string[] = [];
  if (p.verdict_prob != null) bits.push(`P(error) ${p.verdict_prob.toFixed(2)}`);
  if (p.uncertainty != null) bits.push(`u ${p.uncertainty.toFixed(2)}`);
  return bits.join(" · ");
}

export function FlagBubble({ pair, ex, keyUrls, onReview }: {
  pair: PairEvent;
  ex?: Explanation;
  keyUrls: string[];
  onReview: () => void;
}) {
  const a = keyUrls[pair.index];
  const b = keyUrls[pair.index + 1];
  const box = ex?.box;   // fractional [x, y, w, h]
  return (
    <div className="bubble agent flag">
      <div className="bubble-label">
        <span className="flag-dot" aria-hidden="true" /> Pair {pair.index} · {qaLabel(pair.qa)}
        {ex?.err_type ? ` — ${errTypeLabel(ex.err_type)}` : ""}
      </div>
      <div className="trip">
        {a ? <img src={a} alt={`key ${pair.index}`} draggable={false} /> : <span className="trip-hole" />}
        <span className="trip-mid">
          {(ex?.annotated_url || pair.mid_url) ? (
            <img src={ex?.annotated_url ?? pair.mid_url!} alt="in-between (flagged)" draggable={false} />
          ) : <span className="trip-hole" />}
          {!ex?.annotated_url && box && box.length === 4 && (
            <span className="region-box" style={{
              left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
              width: `${box[2] * 100}%`, height: `${box[3] * 100}%`,
            }} title={ex?.region ? `region: ${ex.region}` : "flagged region"} />
          )}
        </span>
        {b ? <img src={b} alt={`key ${pair.index + 1}`} draggable={false} /> : <span className="trip-hole" />}
      </div>
      {ex?.explanation && <p className="flag-why">{ex.explanation}</p>}
      {puLine(pair) && <p className="flag-pu">{puLine(pair)}</p>}
      {pair.correction && pair.correction.rounds.length > 0 && (
        <ul className="trace">
          {pair.correction.rounds.map((r, i) => (
            <li key={i}><code>{r.action}</code> — {r.reason || "…"}</li>
          ))}
          <li className="trace-status"><ArrowRight className="mr-1 inline size-3" aria-hidden="true" />{pair.correction.status}</li>
        </ul>
      )}
      <Button type="button" variant="outline" className="font-mono text-[12.5px] tracking-[0.02em]" onClick={onReview}>Review this pair</Button>
    </div>
  );
}
