// per-pair line-test (flip key_A → in-between → key_B). Extracted from CopilotApp.tsx.
import { useEffect, useState } from "react";

export type Frame = { url: string; label: string };

export function FlipPlayer({ frames }: { frames: Frame[] }) {
  const [playing, setPlaying] = useState(true);
  const [showTween, setShowTween] = useState(true);
  const [i, setI] = useState(0);
  const seq = showTween ? frames.map((_, k) => k) : [0, frames.length - 1];
  useEffect(() => {
    if (!playing || seq.length < 2) return;
    const id = setInterval(() => setI((k) => k + 1), 240); // shoot-on-2s line-test cadence
    return () => clearInterval(id);
  }, [playing, showTween, seq.length]);
  const pos = ((i % seq.length) + seq.length) % seq.length; // safe wrap (step can go negative)
  const cur = seq[pos];
  const step = (d: number) => { setPlaying(false); setI((k) => k + d); };
  return (
    <div className="flip">
      <div className="flip-stage">
        {frames.map((f, k) => (
          <img key={k} src={f.url} alt={f.label} className={k === cur ? "on" : ""} draggable={false} />
        ))}
        <span className="flip-tag">{frames[cur]?.label}</span>
        <span className="flip-count">{pos + 1}/{seq.length}</span>
      </div>
      <div className="flip-ctl">
        <button type="button" className="flip-btn" onClick={() => step(-1)} aria-label="previous frame">◀</button>
        <button type="button" className="flip-btn" onClick={() => setPlaying((pl) => !pl)}>
          {playing ? "❚❚ pause" : "▶ play"}
        </button>
        <button type="button" className="flip-btn" onClick={() => step(1)} aria-label="next frame">▶</button>
        {frames.length > 2 && (
          <label className="flip-toggle">
            <input type="checkbox" checked={showTween} onChange={(e) => setShowTween(e.target.checked)} />
            show in-between
          </label>
        )}
        <span className="flip-hint">line-test · on 2s</span>
      </div>
    </div>
  );
}
