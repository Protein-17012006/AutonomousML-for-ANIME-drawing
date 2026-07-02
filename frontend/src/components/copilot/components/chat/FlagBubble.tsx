// Flagged-pair bubble: triptych + red region-box overlay + QA facts + director trace.
// The overlay uses the EXISTING server-computed fractional box (service/app.py region_box)
// — grid-coarse (3×3 VLM region), honestly not a pixel mask (design §0.5).
import type { CsqBand, Explanation, PairEvent } from "../../types";

function puLine(p: PairEvent): string {
  const bits: string[] = [];
  if (p.verdict_prob != null) bits.push(`P(error) ${p.verdict_prob.toFixed(2)}`);
  if (p.uncertainty != null) bits.push(`u ${p.uncertainty.toFixed(2)}`);
  return bits.join(" · ");
}

export function FlagBubble({ pair, ex, keyUrls, band: _band, onReview }: {
  pair: PairEvent;
  ex?: Explanation;
  keyUrls: string[];
  band?: CsqBand | null;
  onReview: () => void;
}) {
  const a = keyUrls[pair.index];
  const b = keyUrls[pair.index + 1];
  const box = ex?.box;   // fractional [x, y, w, h]
  return (
    <div className="bubble agent flag">
      <div className="bubble-label">
        <span className="flag-dot" aria-hidden="true" /> Pair {pair.index} flagged
        {ex?.err_type ? ` — ${ex.err_type}` : ""}
      </div>
      <div className="trip">
        {a ? <img src={a} alt={`key ${pair.index}`} draggable={false} /> : <span className="trip-hole" />}
        <span className="trip-mid">
          {pair.mid_url ? <img src={pair.mid_url} alt="in-between" draggable={false} /> : <span className="trip-hole" />}
          {box && box.length === 4 && (
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
          <li className="trace-status">→ {pair.correction.status}</li>
        </ul>
      )}
      <button type="button" className="btn btn-ghost" onClick={onReview}>Review this pair</button>
    </div>
  );
}
