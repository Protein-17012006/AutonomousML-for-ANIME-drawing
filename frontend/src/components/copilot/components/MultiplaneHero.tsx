// multiplane camera: a 3D cel-stack that cranes to the cursor (the signature).
// The multiplane camera is cel animation's own 3D rig — glass cels stacked at depth, the lens
// craning through them for true parallax. An in-between IS a cel between cels, so the thesis
// performs itself here: KEY A and KEY B are pulled apart onto far/near glass planes and the
// co-pilot's in-between floats lit between them. One orchestrated moment — the rig tilts to your
// pointer; a single rotation on the preserve-3d stage gives REAL parallax because each plane sits
// at a different Z. Pointer-only and reduced-motion-safe (the rig rests, the cel stops redrawing).
// Extracted from CopilotApp.tsx.
import { useTilt } from "../lib/useTilt";

/* one cel of the line-test, drawn as a self-contained frame on its own glass plane. The figure holds
   the pose for this key (arm down = A, up = B); the in-between cel draws the arm at mid-sweep in
   非-photo-blue, with both key poses ghosting behind so the three read as a sequence (A → 中 → B). */
function CelArt({ kind }: { kind: "a" | "mid" | "b" }) {
  return (
    <svg className="mp-art" viewBox="0 0 160 90" aria-hidden="true">
      <line className="mp-ground" x1="22" y1="80" x2="138" y2="80" />
      {/* the hand's arc around the shoulder — the in-between path the sweep traces */}
      <path className="mp-trajectory" d="M58 56 A 28 28 0 0 1 58 22" />
      {/* the figure: head + a curved gesture spine (line of action) + legs — inked in every cel (the shot) */}
      <g className="mp-figure">
        <circle className="mp-head" cx="80" cy="17" r="7" />
        <path className="mp-spine" d="M80 24 Q 77 41 80 57" />
        <line x1="80" y1="57" x2="69" y2="79" />
        <line x1="80" y1="57" x2="91" y2="79" />
      </g>
      {/* the two KEY arm poses ghost behind every cel so the sweep reads as one shot */}
      <g className="mp-figure-ghost">
        <path d="M80 37 Q 69 49 58 56" />
        <path d="M80 37 Q 69 27 58 22" />
      </g>
      {/* the in-between cel = the anime tell: a faint ao motion SMEAR across the swept arc */}
      {kind === "mid" && <path className="mp-smear" d="M80 37 L58 56 A 28 28 0 0 1 50 39 A 28 28 0 0 1 58 22 Z" />}
      {kind === "a" && <path className="mp-arm-key" d="M80 37 Q 69 49 58 56" />}
      {kind === "b" && <path className="mp-arm-key" d="M80 37 Q 69 27 58 22" />}
      {kind === "mid" && (
        /* the computed in-between arm at mid-sweep, inked in ao, self-drawing over the smear */
        <path className="mp-limb-mid" d="M80 37 Q 65 38 50 39" pathLength={1} />
      )}
    </svg>
  );
}

export function MultiplaneHero() {
  const ref = useTilt();
  return (
    <div className="mplane">
      <div className="mplane-rig" ref={ref}>
        <div className="mplane-stage">
          <span className="mplane-kanji" aria-hidden="true">中</span>
          <div className="mplane-floor" aria-hidden="true" />
          <figure className="mp-cel mp-cel-a">
            <CelArt kind="a" />
            <span className="mp-pegs" aria-hidden="true" />
            <figcaption className="mp-tag">KEY A · 原画</figcaption>
          </figure>
          <figure className="mp-cel mp-cel-mid">
            <CelArt kind="mid" />
            <span className="mp-pegs" aria-hidden="true" />
            <figcaption className="mp-tag mp-tag-ao">in-between · 中割</figcaption>
          </figure>
          <figure className="mp-cel mp-cel-b">
            <CelArt kind="b" />
            <span className="mp-pegs" aria-hidden="true" />
            <figcaption className="mp-tag">KEY B · 原画</figcaption>
          </figure>
        </div>
      </div>
      <div className="mplane-copy">
        <p className="mplane-eyebrow">multiplane line-test</p>
        <h2 className="mplane-thesis">
          It draws the in-between it can <em>stand behind</em> — and asks for your key when it can&rsquo;t.
        </h2>
        <p className="mplane-sub">Load two or more keyframes above, then Run. The co-pilot fills the douga, flags what it&rsquo;s unsure of, and hands the gaps back to you.</p>
      </div>
    </div>
  );
}
