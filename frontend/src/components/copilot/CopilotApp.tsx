"use client";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PairEvent, ResultEvent, DemoResult, Explanation, CsqBand } from "./types";
import { runSession, runDemo, runVideoSession, askQuestion } from "./api";
import { regionLabel, errTypeLabel, actionLabel, readableReason, qaLabel } from "./labels";
import { FilePicker, PegBar } from "./components/Inputs";
import { deriveMessages, type QaTurn, type UserTurn } from "./lib/chatModel";
import { ChatView } from "./components/chat/ChatView";
import { ChatComposer } from "./components/chat/ChatComposer";

/* ---------- file accumulation (dedup by name+size, sorted) ---------- */
function useFileSet() {
  const [files, setFiles] = useState<File[]>([]);
  // `incoming` MUST be a plain array snapshotted at the event (see FilePicker): a live
  // FileList is emptied by the input.value="" reset before this deferred updater runs.
  const add = (incoming: File[]) => {
    if (incoming.length === 0) return;
    setFiles((prev) => {
      const next = [...prev];
      for (const f of incoming) {
        if (!next.some((s) => s.name === f.name && s.size === f.size)) next.push(f);
      }
      next.sort((a, b) => a.name.localeCompare(b.name));
      return next;
    });
  };
  // positional insert (NO re-sort) — the authoritative spot for a drawn breakdown key,
  // kept in lockstep with the server's positional insert at the same index (draw-key loop).
  const insertAt = (pos: number, file: File) => {
    setFiles((prev) => {
      const next = [...prev];
      next.splice(Math.max(0, Math.min(pos, next.length)), 0, file);
      return next;
    });
  };
  // cull a wrong genga before Run (dedup key = name+size, matching `add`)
  const remove = (file: File) =>
    setFiles((prev) => prev.filter((s) => !(s.name === file.name && s.size === file.size)));
  const clear = () => setFiles([]);
  return { files, add, insertAt, remove, clear };
}

/* ---------- decision-log copy helpers ---------- */
function whyText(p: PairEvent): string {
  if (p.action === "needs_key")
    return `Gap too large — draw ${p.keys_requested ?? 1} breakdown key${(p.keys_requested ?? 1) > 1 ? "s" : ""} here`;
  if (p.qa === "pass") return "On-model — the co-pilot is confident";
  if (p.qa === "abstain") return "Unsure — worth a second look";
  if (p.qa === "flag") return "Likely off-model — review / redraw";
  return "";
}
function statusClass(p: PairEvent): string {
  return p.action === "needs_key" ? "needs_key" : p.qa ?? "";
}
/* a shape per status so the state survives without colour (deuteranopia-safe; structure = info) */
function statusGlyph(p: PairEvent): string {
  if (p.action === "needs_key") return "✎";
  if (p.qa === "pass") return "✓";
  if (p.qa === "abstain") return "~";
  if (p.qa === "flag") return "!";
  return "·";
}

/* confidence meter — "% clean" = 1 − P(error) read on a calibrated 180° dial (a measurement,
   not a download). The indicator arc draws itself like the run-loader stroke (pathLength=1 →
   dashoffset = 1 − clean). Raw csq p/u stay in the tooltip (rigor on hover). */
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

/** Resolve the abstain zone (on the dial's "clean" = 1 − p_error axis) for this pair's
 *  uncertainty bin. "forced" = the hard u_max gate makes it always-abstain. */
function abstainZone(p: PairEvent, band?: CsqBand | null): { from: number; to: number } | "forced" | null {
  if (!band) return null;
  const u = p.uncertainty ?? 0;
  if (u > band.u_max) return "forced";
  const e = band.u_edges;
  let j = e.length - 2;
  for (let k = 0; k < e.length - 1; k++) { if (u <= e[k + 1]) { j = k; break; } }
  const tp = band.tau_pass[j], tf = band.tau_flag[j];
  if (tf <= tp) return null;                              // degenerate bin → nothing drawable
  return { from: clamp01(1 - tf), to: clamp01(1 - tp) };  // p_error→clean flips the ends
}

function ConfidenceMeter({ p, band }: { p: PairEvent; band?: CsqBand | null }) {
  if (p.verdict_prob == null || p.action === "needs_key") return null;
  const clean = clamp01(1 - p.verdict_prob);
  const pct = Math.round(clean * 100);
  const tone = p.qa === "pass" ? "pass" : p.qa === "abstain" ? "abstain" : "flag";
  const zone = abstainZone(p, band);
  const arc = "M4 24 A 18 18 0 0 1 40 24";
  return (
    <div className={`confgauge confgauge-${tone}`} title={readableReason(p.reason)}>
      <svg className="confgauge-dial" viewBox="0 0 44 26" aria-hidden="true">
        <path className="cg-track" d={arc} pathLength={1} />
        {zone === "forced" ? (
          <path className="cg-abstain" d={arc} pathLength={1} style={{ strokeDasharray: "1 0" }} />
        ) : zone ? (
          // draw ONLY the [from,to] segment: 0-dash, gap to `from`, visible dash, gap to end
          <path className="cg-abstain" d={arc} pathLength={1}
            style={{ strokeDasharray: `0 ${zone.from} ${zone.to - zone.from} ${1 - zone.to}` }} />
        ) : null}
        <path className="cg-fill" d={arc} pathLength={1} style={{ strokeDashoffset: 1 - clean }} />
      </svg>
      <span className="confgauge-label">
        <b>{pct}%</b> clean
        {zone === "forced"
          ? <i className="cg-zone"> · unsure zone</i>
          : zone ? <i className="cg-zone"> · abstain {Math.round(zone.from * 100)}–{Math.round(zone.to * 100)}%</i> : null}
      </span>
    </div>
  );
}

/* arc path shared by the inline dial + the focused-pair QA panel (a 180° gauge) */
const ARC = "M4 24 A 18 18 0 0 1 40 24";

/* ---------- focused-pair QA panel: the calibrated verdict made the centerpiece (the moat) ----------
   Always shows the FOCUSED pair's read large — a big 180° dial + the calibrated abstain band drawn to
   scale + p_error/uncertainty in plain words + the in-between thumbnail with its akaire region. The
   defensible thing (calibrated 3-state QA) gets an owned surface, not just a 44px inline crumb. */
function QAPanel({ p, band, ex }: { p: PairEvent | null; band?: CsqBand | null; ex?: Explanation }) {
  if (!p) return <div className="qapanel qapanel-empty">Pick a pair (click, or J/K) to see the co-pilot&rsquo;s read.</div>;
  if (p.action === "needs_key") {
    return (
      <div className="qapanel qapanel-needskey">
        <div className="qap-head"><span className="sglyph sglyph-needs_key" aria-hidden="true">✎</span>pair {p.index} · needs a key</div>
        <p className="qap-why">Gap too large to fill reliably — draw a breakdown key here.</p>
      </div>
    );
  }
  const tone = p.qa === "pass" ? "pass" : p.qa === "abstain" ? "abstain" : "flag";
  const hasDial = p.verdict_prob != null;
  const clean = hasDial ? clamp01(1 - (p.verdict_prob as number)) : 0;
  const zone = abstainZone(p, band);
  const rigor = readableReason(p.reason);
  return (
    <div className={`qapanel qapanel-${tone}`}>
      <div className="qap-head">
        <span className={`sglyph sglyph-${statusClass(p)}`} aria-hidden="true">{statusGlyph(p)}</span>
        pair {p.index} · {qaLabel(p.qa)}
      </div>
      <div className="qap-body">
        {hasDial ? (
          // one number on screen ("% clean") + the abstain band drawn to scale; the raw
          // error-likelihood / uncertainty (= the same fact restated) lives in the dial tooltip.
          <div className="qap-gauge" title={rigor}>
            <svg className="qap-dial" viewBox="0 0 44 26" aria-hidden="true">
              <path className="cg-track" d={ARC} pathLength={1} />
              {zone === "forced" ? (
                <path className="cg-abstain" d={ARC} pathLength={1} style={{ strokeDasharray: "1 0" }} />
              ) : zone ? (
                <path className="cg-abstain" d={ARC} pathLength={1}
                  style={{ strokeDasharray: `0 ${zone.from} ${zone.to - zone.from} ${1 - zone.to}` }} />
              ) : null}
              <path className="cg-fill" d={ARC} pathLength={1} style={{ strokeDashoffset: 1 - clean }} />
            </svg>
            <div className="qap-readout">
              <div className="qap-pct"><b>{Math.round(clean * 100)}%</b> clean</div>
              {zone === "forced" ? <div className="qap-zone">unsure zone</div>
                : zone ? <div className="qap-zone">abstain {Math.round(zone.from * 100)}–{Math.round(zone.to * 100)}%</div> : null}
            </div>
          </div>
        ) : (
          <div className="qap-readout">
            <div className="qap-pct"><b>{qaLabel(p.qa)}</b></div>
            <div className="qap-rigor">no calibrated score (demo engine)</div>
          </div>
        )}
      </div>
      {ex && <div className="qap-explain">✎ {errTypeLabel(ex.err_type)}{regionLabel(ex.region) ? `, ${regionLabel(ex.region)}` : ""} — {ex.explanation}</div>}
    </div>
  );
}

/* ---------- hidden file input + styled label trigger ---------- */
/* FilePicker / PegBar / KeyframeDropzone / shortName moved to components/Inputs.tsx;
   the old Console header is superseded by the chat composer (chat-first surface). */

/* ---------- per-pair line-test (flip key_A → in-between → key_B) ---------- */
type Frame = { url: string; label: string };

function FlipPlayer({ frames }: { frames: Frame[] }) {
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

/* ---------- reconstructed-cut transport: X-sheet rail + frame-accurate step (rVFC) ---------- */
function ReconPlayer({ src, fps }: { src: string; fps: number }) {
  const vref = useRef<HTMLVideoElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);     // currentTime (s)
  const [dur, setDur] = useState(0); // duration (s)

  // frame-accurate playhead via requestVideoFrameCallback; fallback to timeupdate
  useEffect(() => {
    const v = vref.current as (HTMLVideoElement & {
      requestVideoFrameCallback?: (cb: (now: number, m: { mediaTime: number }) => void) => number;
      cancelVideoFrameCallback?: (h: number) => void;
    }) | null;
    if (!v) return;
    if (v.requestVideoFrameCallback) {
      let h = 0;
      const cb = (_n: number, m: { mediaTime: number }) => { setT(m.mediaTime); h = v.requestVideoFrameCallback!(cb); };
      h = v.requestVideoFrameCallback(cb);
      return () => { try { v.cancelVideoFrameCallback?.(h); } catch { /* noop */ } };
    }
    const on = () => setT(v.currentTime);
    v.addEventListener("timeupdate", on);
    return () => v.removeEventListener("timeupdate", on);
  }, [src]);

  const frame = Math.round(t * fps);
  const total = Math.max(1, Math.round(dur * fps));
  const pct = dur ? (t / dur) * 100 : 0;

  const toggle = () => {
    const v = vref.current;
    if (!v) return;
    if (v.paused) void v.play(); else v.pause();
  };
  const step = (d: number) => {
    const v = vref.current;
    if (!v) return;
    v.pause();
    v.currentTime = Math.max(0, Math.min(dur || 0, (Math.round(t * fps) + d) / fps + 1e-4)); // snap to the douga cell
  };
  const seek = (clientX: number) => {
    const v = vref.current, el = railRef.current;
    if (!v || !el || !dur) return;
    const r = el.getBoundingClientRect();
    v.currentTime = Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * dur;
  };

  return (
    <div className="rplayer">
      <video
        id="recon-video"
        ref={vref}
        src={src}
        playsInline
        onLoadedMetadata={() => setDur(vref.current?.duration || 0)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onClick={toggle}
      />
      <div className="rplayer-ctl">
        <button type="button" className="rbtn" onClick={() => step(-1)} aria-label="previous frame">◀</button>
        <button type="button" className="rbtn rbtn-play" onClick={toggle} aria-label={playing ? "pause" : "play"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button type="button" className="rbtn" onClick={() => step(1)} aria-label="next frame">▶</button>
        <div
          className="rplayer-rail"
          ref={railRef}
          role="slider"
          aria-label="scrub the reconstructed cut"
          aria-valuenow={frame}
          aria-valuemin={0}
          aria-valuemax={total}
          tabIndex={0}
          onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); seek(e.clientX); }}
          onPointerMove={(e) => { if (e.buttons) seek(e.clientX); }}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); } else if (e.key === "ArrowRight") { e.preventDefault(); step(1); } }}
        >
          <span className="rplayer-fill" style={{ width: `${pct}%` }} />
          <span className="rplayer-head" style={{ left: `${pct}%` }} />
        </div>
        <span className="rplayer-count">{String(frame).padStart(3, "0")}<i>/{total}</i></span>
      </div>
    </div>
  );
}

/* ---------- self-drawing run loader (a cel + peg-bar drawing themselves) ---------- */
function RunLoader() {
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

/* ---------- toast: a correction-stamp slide-in for run errors (akaire body, draining ao timer) ---------- */
function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // auto-dismiss; the timer resets only on a NEW message (App keys the toast by message)
  useEffect(() => {
    const id = window.setTimeout(() => closeRef.current(), 5200);
    return () => window.clearTimeout(id);
  }, [message]);
  return (
    <div className="toast" role="alert">
      <span className="toast-mark" aria-hidden="true" />
      <span className="toast-msg">{message}</span>
      <button type="button" className="toast-x" onClick={onClose} aria-label="dismiss">×</button>
      <span className="toast-timer" aria-hidden="true" />
    </div>
  );
}

/* ---------- multiplane camera: a 3D cel-stack that cranes to the cursor (the signature) ----------
   The multiplane camera is cel animation's own 3D rig — glass cels stacked at depth, the lens
   craning through them for true parallax. An in-between IS a cel between cels, so the thesis
   performs itself here: KEY A and KEY B are pulled apart onto far/near glass planes and the
   co-pilot's in-between floats lit between them. One orchestrated moment — the rig tilts to your
   pointer; a single rotation on the preserve-3d stage gives REAL parallax because each plane sits
   at a different Z. Pointer-only and reduced-motion-safe (the rig rests, the cel stops redrawing). */
function useTilt<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!window.matchMedia("(pointer: fine)").matches) return; // no cursor → leave the rig at rest
    const set = (mx: number, my: number) => {
      el.style.setProperty("--mx", String(mx));
      el.style.setProperty("--my", String(my));
    };
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      set(((e.clientX - r.left) / r.width - 0.5) * 2, ((e.clientY - r.top) / r.height - 0.5) * 2);
    };
    const onLeave = () => set(0, 0);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => { el.removeEventListener("pointermove", onMove); el.removeEventListener("pointerleave", onLeave); };
  }, []);
  return ref;
}

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

function MultiplaneHero() {
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

/* DemoHero removed (P2): the multiplane hero is the single signature; the right-column
   cold-start uses RunLoader, so a second bouncing-ball thesis no longer competes with it. */

/* ---------- right-column frame trip: static key·in-between·key, or a big line-test on play ---------- */
function FrameTrip({ p, a, b, mid, ex }: { p: PairEvent; a?: string; b?: string; mid?: string; ex?: Explanation }) {
  const [play, setPlay] = useState(false);
  const canPlay = !!(a && b);
  const frames: Frame[] = mid && a && b
    ? [{ url: a, label: "key A" }, { url: mid, label: "in-between" }, { url: b, label: "key B" }]
    : a && b ? [{ url: a, label: "key A" }, { url: b, label: "key B" }] : [];
  return (
    <>
      <figcaption>
        <span className={`sglyph sglyph-${statusClass(p)}`} aria-hidden="true">{statusGlyph(p)}</span>
        pair {p.index} · {actionLabel(p.action)}{p.qa ? ` · ${qaLabel(p.qa)}` : ""}
        {canPlay && (
          <button type="button" className="trip-play"
            onClick={(e) => { e.stopPropagation(); setPlay((v) => !v); }}>
            {play ? "▦ frames" : "▶ play"}
          </button>
        )}
      </figcaption>
      {play && frames.length >= 2 ? (
        <div className="trip-player"><FlipPlayer frames={frames} /></div>
      ) : (
        <div className="frametrip">
          {a ? <img src={a} alt="key A" /> : <div className="fcell-empty">A</div>}
          {mid ? (
            <div className="fcell-wrap">
              <img src={mid} alt="in-between" />
              {ex?.box && ex.box.length === 4 && (
                // the akaire correction box, with a 作監-style margin tag naming the defect,
                // tethered to the exact region so the frame, the place, and the why read as one note
                <span className="region-box"
                  style={{ left: `${ex.box[0] * 100}%`, top: `${ex.box[1] * 100}%`, width: `${ex.box[2] * 100}%`, height: `${ex.box[3] * 100}%` }}>
                  <span className="region-tag">✎ {errTypeLabel(ex.err_type)}</span>
                </span>
              )}
            </div>
          ) : p.action === "needs_key" ? (
            <div className="fcell-draw">✎ draw a key here</div>
          ) : (
            <div className="fcell-empty">in-between</div>
          )}
          {b ? <img src={b} alt="key B" /> : <div className="fcell-empty">B</div>}
        </div>
      )}
    </>
  );
}

/* ---------- one reviewed pair as a mini multiplane rig (cursor-craned, carries the hero's grammar) ----------
   The right-column work item reuses the landing's multiplane camera: on hover the three cells separate onto
   glass planes (the two keys recede, the co-pilot's in-between lifts forward + lit) and the rig cranes to the
   cursor. The thing under QA is physically presented forward — depth that does a job, not decoration. */
function FrameCard({ p, a, b, mid, ex, i, focused, onFocus }: {
  p: PairEvent; a?: string; b?: string; mid?: string; ex?: Explanation;
  i: number; focused: boolean; onFocus: () => void;
}) {
  return (
    <figure
      id={`frow-${p.index}`}
      data-pair={p.index}
      style={{ "--i": Math.min(i, 12) } as React.CSSProperties}
      className={`frameset ${statusClass(p)}${focused ? " focused" : ""}`}
      onClick={onFocus}
    >
      <FrameTrip p={p} a={a} b={b} mid={mid} ex={ex} />
    </figure>
  );
}

/* ---------- review workbench: two scroll-synced columns ---------- */
type Filter = "offmodel" | "unsure" | "pass" | "all" | "needs_key";

/** Export the usable result: the box already built the reconstructed video + in-between
 *  frames + montage into the session dir; /bundle.zip zips them for one-click download. */
function downloadBundle(result: ResultEvent | null) {
  const art = result?.artifacts;
  if (!art) return;
  const ref = art.video || art.montage;           // any artifact shares /session/{sid}/…
  const bundleUrl = ref.replace(/\/[^/]+$/, "/bundle.zip");
  const a = document.createElement("a");
  a.href = bundleUrl;
  a.download = "copilot_session.zip";
  a.click();
}

/** The artist-κ deliverable: the model's self-QA verdict × the artist's accept/reject per filled pair.
 *  This is the independent κ ground-truth the project lacks — written client-side to review.json so the
 *  artist's review work isn't thrown away (the bundle zip carries pixels; this carries the labels). */
function downloadReview(log: PairEvent[], verdicts: Record<number, "accept" | "reject">) {
  const pairs = log.filter((p) => p.action !== "needs_key").map((p) => ({
    pair: p.index,
    model_qa: p.qa ?? null,
    model_reason: p.reason ?? null,
    verdict_prob: p.verdict_prob ?? null,
    artist: verdicts[p.index] ?? null,
  }));
  const doc = { reviewed: pairs.filter((r) => r.artist).length, total: pairs.length, pairs };
  const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "review.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function ReviewWorkbench({ log, result, running, keyUrls, verdicts, onVerdict, onRefill, compareSlot, fps, initialFocus }: {
  log: PairEvent[];
  result: ResultEvent | null;
  running: boolean;
  keyUrls: string[];
  verdicts: Record<number, "accept" | "reject">;
  onVerdict: (idx: number, v: "accept" | "reject") => void;
  onRefill: (index: number, file: File) => void;
  compareSlot: React.ReactNode;
  fps: number;
  initialFocus?: number | null;   // chat "Review this pair" deep-link
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [focused, setFocused] = useState<number | null>(initialFocus ?? null);
  // re-entering the board from a different chat bubble refocuses that pair
  useEffect(() => { if (initialFocus != null) setFocused(initialFocus); }, [initialFocus]);
  const [exported, setExported] = useState(false);              // Export ⤓ → clean-cel ✓ morph
  const [glider, setGlider] = useState({ left: 0, width: 0 });  // sliding "current-cel" triage marker
  const [reconOpen, setReconOpen] = useState(false);            // the reconstructed-cut band (collapsed until invoked — payoff shouldn't steal the triage fold)
  const pickedRef = useRef(false);                              // did the artist choose a filter this run?
  const autoTriagedRef = useRef(false);                         // has the worst-first auto-triage fired this run?
  const tabsRef = useRef<HTMLDivElement>(null);
  const explanations = result?.explanations;
  const mids = result?.pair_mids;
  const samp = result?.sampling;   // drop-a-video decimation summary (null for PNG upload)
  const video = result?.artifacts?.video;

  const filled = log.filter((p) => p.action !== "needs_key");
  const gaps = log.filter((p) => p.action === "needs_key");
  const offmodel = filled.filter((p) => p.qa === "flag");
  const unsure = filled.filter((p) => p.qa === "abstain");
  const passed = filled.filter((p) => p.qa === "pass");
  // cadence read-out (the "45fps not 60" principle made visible): holds were COPIED + snaps KEPT
  // their timing; only genuine small motion was interpolated. Routes come straight from the gate.
  const holds = filled.filter((p) => p.route === "hold").length;
  const snaps = filled.filter((p) => p.route === "snap_preserve").length;
  const interpd = filled.filter((p) => p.route === "rife").length;
  const shown = filter === "offmodel" ? offmodel : filter === "unsure" ? unsure : filter === "pass" ? passed : filter === "needs_key" ? gaps : filled;
  const reviewedCount = filled.filter((p) => verdicts[p.index]).length;
  const pending = Math.max(0, keyUrls.length - 1 - log.length);   // pairs still being inked (live run)
  // the pair the QA panel inspects: the focused one, else the first in the current view
  const panelPair = (focused != null ? log.find((p) => p.index === focused) : null) ?? shown[0] ?? null;

  // plain-language result headline + a "play your cut" CTA (frames the payoff after a run)
  const headline = result
    ? [
        `Filled ${filled.length} in-between${filled.length === 1 ? "" : "s"}`,
        offmodel.length + unsure.length === 0 ? "all clean" : `${offmodel.length + unsure.length} to review`,
        ...(gaps.length > 0 ? [`${gaps.length} key${gaps.length === 1 ? "" : "s"} to draw`] : []),
      ].join(" · ")
    : null;
  const playCut = () => {
    // open if collapsed, then play. NO scrollIntoView: the band is flex:none right below the toolbar
    // (already in view when open), so scrolling to it is pointless — and on a 2nd click it re-scrolled
    // the overflow:hidden app shell (programmatically scrollable), shifting the layout and revealing the
    // band's bottom border + the columns below (the reported "viền dưới" jank).
    setReconOpen(true);
    requestAnimationFrame(() => {
      const v = document.getElementById("recon-video") as HTMLVideoElement | null;
      v?.play().catch(() => {});
    });
  };

  /* --- two-column scroll sync by pair (scroll one → align the other to same pair) --- */
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const active = useRef<"L" | "R" | null>(null);
  const rafing = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  // cached [data-pair] offsets per column — so scroll-sync doesn't force a layout read PER ROW
  // PER FRAME (at 200+ rows the old querySelectorAll + offsetTop-per-row each scroll frame stutters).
  // Rebuilt on layout-affecting change (filter/log/result/resize); the sync itself is then pure math.
  const offCache = useRef<{ L: { pair: number; top: number }[]; R: { pair: number; top: number }[] }>({ L: [], R: [] });
  const offMap = useRef<{ L: Map<number, number>; R: Map<number, number> }>({ L: new Map(), R: new Map() });
  const rebuildOffsets = () => {
    (["L", "R"] as const).forEach((k) => {
      const el = k === "L" ? leftRef.current : rightRef.current;
      if (!el) return;
      const arr: { pair: number; top: number }[] = [];
      const m = new Map<number, number>();
      el.querySelectorAll<HTMLElement>("[data-pair]").forEach((r) => {
        const pair = Number(r.dataset.pair);
        const top = r.offsetTop;
        arr.push({ pair, top });
        m.set(pair, top);
      });
      offCache.current[k] = arr;
      offMap.current[k] = m;
    });
  };
  const sync = (from: "L" | "R") => {
    if (active.current && active.current !== from) return; // ignore the echo from the synced column
    active.current = from;
    if (!rafing.current) {
      rafing.current = true;
      requestAnimationFrame(() => {
        rafing.current = false;
        const src = from === "L" ? leftRef.current : rightRef.current;
        const dst = from === "L" ? rightRef.current : leftRef.current;
        if (!src || !dst) return;
        const arr = offCache.current[from];
        if (arr.length === 0) return;
        const st = src.scrollTop;                          // pure arithmetic over cached tops — no layout
        let pair = arr[0].pair, best = Infinity;
        for (const e of arr) { const d = Math.abs(e.top - st); if (d < best) { best = d; pair = e.pair; } }
        const dtop = offMap.current[from === "L" ? "R" : "L"].get(pair);
        if (dtop != null) dst.scrollTop = dtop;
      });
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { active.current = null; }, 140);
  };

  /* --- keyboard review loop (attach once, read live state via refs) --- */
  const shownRef = useRef(shown); shownRef.current = shown;
  const focusedRef = useRef(focused); focusedRef.current = focused;
  const verdictRef = useRef(onVerdict); verdictRef.current = onVerdict;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      // don't hijack keys while a slider rail (scrub / wipe) has focus, or in a contentEditable
      if (el?.isContentEditable || el?.closest?.('[role="slider"]')) return;
      const list = shownRef.current;
      if (list.length === 0) return;
      const cur = list.findIndex((p) => p.index === focusedRef.current);
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setFocused(list[Math.min(list.length - 1, (cur < 0 ? -1 : cur) + 1)].index);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setFocused(list[Math.max(0, (cur < 0 ? 1 : cur) - 1)].index);
      } else if (e.key === "a" || e.key === "x") {
        // verdict acts ONLY on an explicitly focused row — never a blind list[0].
        // J/K establish focus first; A/X with nothing focused is a no-op.
        if (cur < 0) return;
        verdictRef.current(list[cur].index, e.key === "a" ? "accept" : "reject");
        setFocused(list[Math.min(list.length - 1, cur + 1)].index);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  // keep focus valid across filter switches: if the focused pair left the view, pin to the
  // nearest still-visible pair instead of silently orphaning focus (so the next J/K doesn't jump to top)
  useEffect(() => {
    if (focused == null) return;
    if (shown.some((p) => p.index === focused)) return;
    if (shown.length === 0) { setFocused(null); return; }
    const nearest = shown.reduce((best, p) =>
      Math.abs(p.index - focused) < Math.abs(best.index - focused) ? p : best, shown[0]);
    setFocused(nearest.index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  // worst-first: when a run completes, open the triage on the most urgent state and focus its first
  // pair (so the QA panel opens on the verdict that needs eyes), unless the artist already chose a filter.
  useEffect(() => {
    if (!result) { pickedRef.current = false; autoTriagedRef.current = false; return; }
    if (autoTriagedRef.current) return;   // only the FIRST result of a run auto-triages — never yank a mid-review artist on a draw-key refill
    autoTriagedRef.current = true;
    if (!pickedRef.current) setFilter(offmodel.length ? "offmodel" : unsure.length ? "unsure" : "all");
    if (focused == null) {
      const first = offmodel[0] ?? unsure[0] ?? filled[0];
      if (first) setFocused(first.index);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  // focus → scroll the left into view; the sync pulls the right to the same pair
  useEffect(() => {
    if (focused == null) return;
    leftRef.current?.querySelector<HTMLElement>(`[data-pair="${focused}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  const pick = (f: Filter) => { pickedRef.current = true; setFilter(f); };
  const chip = (key: Filter, label: string, n: number, title: string) => (
    <button type="button" className={`chip chip-${key}${filter === key ? " on" : ""}`}
      title={title} onClick={() => pick(key)}>
      {label} <b>{n}</b>
    </button>
  );
  const filterDesc: Record<Filter, string> = {
    offmodel: "In-betweens the co-pilot thinks are off-model — review / redraw these first.",
    unsure: "In-betweens the co-pilot won't vouch for — worth a second look.",
    pass: "In-betweens the co-pilot is confident are on-model — skim, then accept.",
    all: "Every in-between the co-pilot filled (on-model + unsure + off-model).",
    needs_key: "Pairs whose two keys are too far apart to fill — draw a breakdown key between them.",
  };
  const flipFrames = (p: PairEvent): Frame[] | null => {
    const a = keyUrls[p.index];
    const b = keyUrls[p.index + 1];
    if (!a || !b) return null;
    const mid = p.mid_url ?? mids?.[String(p.index)]; // live per-pair, fallback to result
    return mid
      ? [{ url: a, label: "key A" }, { url: mid, label: "in-between" }, { url: b, label: "key B" }]
      : [{ url: a, label: "key A" }, { url: b, label: "key B" }];
  };

  // slide the triage glider to the active chip (variable-width mono labels → measure live)
  useLayoutEffect(() => {
    const on = tabsRef.current?.querySelector<HTMLElement>(".chip.on");
    if (on) setGlider({ left: on.offsetLeft, width: on.offsetWidth });
  }, [filter, offmodel.length, unsure.length, passed.length, filled.length, gaps.length]);

  // rebuild the scroll-sync offset cache whenever the rendered row set changes (filter/log/result),
  // and on resize — so sync() never has to query the DOM or read offsetTop during a scroll.
  useLayoutEffect(() => { rebuildOffsets(); }, [filter, shown.length, log.length, result]);
  useEffect(() => {
    const onResize = () => rebuildOffsets();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      {log.length > 0 && (
        <div className="toolbar">
          {headline && (
            <div className="headline">
              <span className="headline-text">{headline}</span>
              {video && <button type="button" className="headline-play" onClick={playCut}>▶ Play your cut</button>}
            </div>
          )}
          {result && filled.length > 0 && (
            <p className="cadence" title="Holds are copied and snaps keep their timing — the co-pilot only interpolates genuine small motion, so the original on-2s/on-3s cadence is preserved.">
              <span className="cadence-mark" aria-hidden="true" />
              {holds + snaps > 0
                ? <>cadence kept — <b>{holds}</b> held · <b>{snaps}</b> snapped · <b>{interpd}</b> interpolated</>
                : <><b>{interpd}</b> in-between{interpd === 1 ? "" : "s"} interpolated</>}
              <span className="cadence-tag">45fps · not 60</span>
            </p>
          )}
          <div className="triage">
            <div className="triage-tabs" ref={tabsRef}
              data-tone={filter === "offmodel" || filter === "needs_key" ? "akaire" : filter === "unsure" ? "abstain" : "ao"}>
              <span className="triage-glider" aria-hidden="true"
                style={{ transform: `translateX(${glider.left}px)`, width: glider.width }} />
              {chip("offmodel", "Off-model", offmodel.length, "In-betweens the co-pilot thinks are off-model — review / redraw")}
              {chip("unsure", "Unsure", unsure.length, "In-betweens the co-pilot won't vouch for — a second look")}
              {chip("pass", "On-model", passed.length, "In-betweens the co-pilot is confident are on-model")}
              {chip("all", "All filled", filled.length, "Everything the co-pilot interpolated")}
              {gaps.length > 0 && chip("needs_key", "Needs key", gaps.length, "Gaps too large to fill — draw a breakdown key")}
            </div>
            <span className="triage-progress">
              {reviewedCount}/{filled.length} reviewed
              {result && <> · {result.n_autopass} pass · {result.flagged.length} flag · {result.keys_requested_total} key</>}
            </span>
            <button type="button" className={`export-btn${exported ? " done" : ""}`} disabled={!result}
              title={result ? "Download the reconstructed video + frames (.zip) AND your accept/reject review (review.json — the artist-κ data)" : "Run the co-pilot first"}
              onClick={() => { downloadBundle(result); downloadReview(log, verdicts); setExported(true); window.setTimeout(() => setExported(false), 1600); }}>
              {exported ? "Exported ✓" : "Export ⤓"}</button>
          </div>
          <div className="toolbar-foot">
            <p className="filter-desc">{filterDesc[filter]}</p>
            <p className="kbd-hint">⌨ J/K · A keep · X redraw · columns scroll-synced</p>
          </div>
        </div>
      )}

      {log.length === 0 && !running ? (
        /* landing thesis: the multiplane camera performs the in-between before the desk fills with work */
        <main className="landing">
          <MultiplaneHero />
          {compareSlot}
        </main>
      ) : (
      <>
      {samp && (
        /* drop-a-video transparency: how the clip was decimated into keys, and a warning when
           the stride was auto-coarsened (the reconstruction samples the source, not every frame). */
        <div className={`sampling-note${samp.stride > samp.requested_stride ? " warn" : ""}`}>
          {samp.stride > samp.requested_stride
            ? `⚠ Long clip — auto-coarsened to 1 key every ${samp.stride} frames (kept ${samp.kept} of ${samp.source_frames}). This samples the cut, not every frame; trim to a single short cut for a faithful reconstruction.`
            : `Decimated: kept ${samp.kept} keys of ${samp.source_frames} frames (1 every ${samp.stride}).`}
        </div>
      )}
      {video && (
        /* the reconstructed cut = the payoff, a full-width band above the columns (collapsible) */
        <div className={`recon-band${reconOpen ? "" : " is-collapsed"}`}>
          <button type="button" className="recon-band-head" aria-expanded={reconOpen} onClick={() => setReconOpen((o) => !o)}>
            <span className="recon-band-caret" aria-hidden="true">{reconOpen ? "▾" : "▸"}</span>
            <span className="eyebrow">出力</span>
            <span className="recon-band-title">Reconstructed cut</span>
            {!reconOpen && <span className="recon-band-hint">▶ play the filled cut</span>}
          </button>
          {reconOpen && <div className="recon-band-body"><ReconPlayer src={video} fps={fps} /></div>}
        </div>
      )}
      <main className="dual">
        {/* LEFT: review controls */}
        <section className="pane col-left" ref={leftRef} onScroll={() => sync("L")}>
          {log.length > 0 && (
            <QAPanel
              p={panelPair}
              band={result?.csq}
              ex={panelPair ? explanations?.[String(panelPair.index)] : undefined}
            />
          )}
          {running && shown.length === 0 ? (
            <RunLoader />
          ) : log.length === 0 ? (
            <p className="log-empty">
              Load two or more keyframes, then Run. The co-pilot fills what it can and flags the rest — review the
              suspect in-betweens here (flip key&nbsp;→&nbsp;in-between&nbsp;→&nbsp;key), with the big frames synced
              on the right.
            </p>
          ) : shown.length === 0 ? (
            <p className="log-empty">
              {filter === "offmodel" || filter === "unsure"
                ? "Nothing here — the co-pilot is confident about every in-between. 🎉"
                : "No in-betweens in this view."}
            </p>
          ) : (
            <ol className="log" key={filter}>
              {shown.map((p, i) => {
                const ex = explanations?.[String(p.index)];
                const frames = flipFrames(p);
                const v = verdicts[p.index];
                return (
                  <li
                    key={p.index}
                    id={`row-${p.index}`}
                    data-pair={p.index}
                    // --i drives the staggered cel-in delay: on a filter remount the cels land
                    // peg-by-peg down the sheet; capped so a long run never lags the tail.
                    style={{ "--i": Math.min(i, 12) } as React.CSSProperties}
                    className={`${statusClass(p)}${focused === p.index ? " focused" : ""}${v ? " v-" + v : ""}`}
                    onClick={() => setFocused(p.index)}
                  >
                    <div className="log-head">
                      <span className={`sglyph sglyph-${statusClass(p)}`} aria-hidden="true">{statusGlyph(p)}</span>
                      pair {p.index} · {actionLabel(p.action)}{p.qa ? ` · ${qaLabel(p.qa)}` : ""}
                      {v && <span className={`verdict-badge ${v}`}>{v === "accept" ? "✓ kept" : "✗ redraw"}</span>}
                    </div>
                    <div className="log-why">{whyText(p)}</div>
                    {/* the gauge earns its place where the decision is live (abstain/flag); a clean
                        pass is already settled, so it stays quiet — fewer dials, calmer list */}
                    {p.qa !== "pass" && <ConfidenceMeter p={p} band={result?.csq} />}
                    {ex && <div className="log-explain">✎ {errTypeLabel(ex.err_type)}{regionLabel(ex.region) ? `, ${regionLabel(ex.region)}` : ""} — {ex.explanation}</div>}
                    {frames && <FlipPlayer frames={frames} />}
                    {p.action !== "needs_key" ? (
                      <div className="verdict">
                        <span className="verdict-label">Your call</span>
                        <button type="button" className={`vbtn accept${v === "accept" ? " on" : ""}`}
                          onClick={(e) => { e.stopPropagation(); onVerdict(p.index, "accept"); }}>✓ Keep</button>
                        <button type="button" className={`vbtn reject${v === "reject" ? " on" : ""}`}
                          onClick={(e) => { e.stopPropagation(); onVerdict(p.index, "reject"); }}>✗ Redraw</button>
                      </div>
                    ) : (
                      <label className="addkey" onClick={(e) => e.stopPropagation()}>
                        <input type="file" accept="image/png" className="visually-hidden"
                          onChange={(e) => { const f = e.currentTarget.files?.[0]; e.currentTarget.value = ""; if (f) onRefill(p.index, f); }} />
                        <span className="btn-addkey">✎ Add my key</span>
                      </label>
                    )}
                  </li>
                );
              })}
            </ol>
          )}

          {running && pending > 0 && shown.length > 0 && (
            <ul className="skel-list" aria-hidden="true">
              {Array.from({ length: Math.min(pending, 6) }).map((_, i) => (
                <li className="cel-skel" key={i} style={{ "--i": i } as React.CSSProperties}>
                  <span className="skel-line skel-head" />
                  <span className="skel-line skel-why" />
                  <span className="skel-trip"><i /><i /><i /></span>
                </li>
              ))}
            </ul>
          )}

          {gaps.length > 0 && filter !== "needs_key" && (
            <div className="gaps">
              <button type="button" className="gaps-head" onClick={() => pick("needs_key")}>
                <span className="gaps-mark" aria-hidden="true" />
                {gaps.length} gap{gaps.length > 1 ? "s" : ""} too large — draw a key here
                <span className="gaps-toggle">view →</span>
              </button>
            </div>
          )}
        </section>

        {/* RIGHT: big per-pair frames (key A · in-between · key B), synced */}
        <section className="pane col-right" ref={rightRef} onScroll={() => sync("R")}>
          <div className="frames-head">
            <span className="eyebrow">出力 frames</span>
            <h2>key · in-between · key</h2>
          </div>
          {running && log.length === 0 ? (
            <RunLoader />
          ) : shown.length === 0 ? (
            <p className="log-empty">No in-betweens in this view.</p>
          ) : (
            <div className="frames-list" key={filter}>{shown.map((p, i) => {
              const a = keyUrls[p.index];
              const b = keyUrls[p.index + 1];
              const mid = p.mid_url ?? mids?.[String(p.index)]; // live per-pair, fallback to result
              const ex = explanations?.[String(p.index)];
              return (
                <FrameCard key={p.index} p={p} a={a} b={b} mid={mid} ex={ex} i={i}
                  focused={focused === p.index} onFocus={() => setFocused(p.index)} />
              );
            })}</div>
          )}
        </section>
      </main>
      </>
      )}
    </>
  );
}

/* ---------- before/after wipe: drag SOURCE↔RIFE through the SAME frame (clip-path inset) ---------- */
function CompareWipe({ orig, rife }: { orig: string; rife: string }) {
  const [pos, setPos] = useState(50);                  // divider, % from the left
  const stageRef = useRef<HTMLDivElement>(null);
  const aRef = useRef<HTMLVideoElement>(null);         // ORIGINAL (bottom layer)
  const bRef = useRef<HTMLVideoElement>(null);         // RECON/RIFE (top, clipped from the divider rightward)
  const dragging = useRef(false);

  // keep the two cuts on the same douga frame — the original drives, the recon follows its clock
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const a = aRef.current, b = bRef.current;
      if (a && b && Math.abs(b.currentTime - a.currentTime) > 0.04) b.currentTime = a.currentTime;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const moveTo = (clientX: number) => {
    const el = stageRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos(Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100)));
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); setPos((p) => Math.max(0, p - 2)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setPos((p) => Math.min(100, p + 2)); }
    else if (e.key === "Home") setPos(0);
    else if (e.key === "End") setPos(100);
  };

  return (
    <div
      className="cmpwipe"
      ref={stageRef}
      style={{ "--pos": `${pos}%` } as React.CSSProperties}
      onPointerDown={(e) => { dragging.current = true; (e.target as Element).setPointerCapture?.(e.pointerId); moveTo(e.clientX); }}
      onPointerMove={(e) => { if (dragging.current) moveTo(e.clientX); }}
      onPointerUp={() => { dragging.current = false; }}
      onPointerLeave={() => { dragging.current = false; }}
    >
      <video ref={aRef} className="cmpwipe-a" src={orig} autoPlay muted loop playsInline />
      <video ref={bRef} className="cmpwipe-b" src={rife} autoPlay muted loop playsInline />
      <span className="cmpwipe-tag cmpwipe-tag-l">SOURCE 原画</span>
      <span className="cmpwipe-tag cmpwipe-tag-r">RIFE 中割</span>
      <div
        className="cmpwipe-divider"
        role="slider"
        tabIndex={0}
        aria-label="wipe between the original cut and the RIFE reconstruction"
        aria-valuenow={Math.round(pos)} aria-valuemin={0} aria-valuemax={100}
        onKeyDown={onKeyDown}
      >
        <span className="cmpwipe-grip" aria-hidden="true">◀ ▶</span>
      </div>
    </div>
  );
}

/* ---------- compare / demo ---------- */
interface CompareProps {
  files: File[];
  onAdd: (files: File[]) => void;
  onClear: () => void;
  onBuild: () => void;
  building: boolean;
  banner: string | null;
  result: DemoResult | null;
}
function Compare(p: CompareProps) {
  const [open, setOpen] = useState(false);
  return (
    <section className="compare">
      <button type="button" className="compare-head" onClick={() => setOpen((o) => !o)}>
        <span className="eyebrow">比較 compare</span>
        <span className="compare-title">See it on a real cut</span>
        <span className="compare-toggle">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="compare-body">
          <p className="hint">
            Upload a <b>full cut</b> (every frame, named 0000.png, 0001.png…). The system drops every other frame,
            then RIFE reconstructs them — <b>left = source</b> · <b>right = RIFE</b>. Set <code>engine</code> + <code>fps</code> above.
          </p>
          <div className="controls">
            <FilePicker id="demokeys" label="Load full cut" onAdd={p.onAdd} />
            <button type="button" className="btn btn-quiet" onClick={p.onClear}>Clear</button>
            <button className="btn btn-primary" disabled={p.files.length < 3 || p.building} onClick={p.onBuild}>
              {p.building ? "Building…" : "Build comparison"}
            </button>
          </div>
          {p.files.length > 0 && <div className="filelist">{p.files.length} frame(s) (full cut)</div>}
          {p.banner && <div className="banner">{p.banner}</div>}
          {p.building && <p className="filelist">building… (RIFE runs on the box; this can take a moment)</p>}
          {p.result && (
            <>
              {p.result.video_orig && p.result.video_rife ? (
                <CompareWipe orig={p.result.video_orig} rife={p.result.video_rife} />
              ) : (
                <div className="screen"><video src={p.result.video} controls /></div>
              )}
              <p className="filelist demo-summary">
                {p.result.frames} frames → {p.result.src} keys + {p.result.gt} GT · drag the divider · left source · right RIFE
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}

/* ---------- app ---------- */
export default function App() {
  const keys = useFileSet();
  const demo = useFileSet();
  const [engines, setEngines] = useState("box");
  const [fps, setFps] = useState("24");

  const [running, setRunning] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [log, setLog] = useState<PairEvent[]>([]);
  const [result, setResult] = useState<ResultEvent | null>(null);
  const [verdicts, setVerdicts] = useState<Record<number, "accept" | "reject">>({});
  const setVerdict = (idx: number, v: "accept" | "reject") =>
    setVerdicts((prev) => {
      const n = { ...prev };
      if (n[idx] === v) delete n[idx]; // toggle off
      else n[idx] = v;
      return n;
    });

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [stride, setStride] = useState("2");

  const [demoBuilding, setDemoBuilding] = useState(false);
  const [demoBanner, setDemoBanner] = useState<string | null>(null);
  const [demoResult, setDemoResult] = useState<DemoResult | null>(null);

  // chat-first surface state (vault 'Chat-First Copilot Surface')
  const [view, setView] = useState<"chat" | "board">("chat");
  const [boardFocus, setBoardFocus] = useState<number | null>(null);
  const [upload, setUpload] = useState<UserTurn | null>(null);
  const [qaTurns, setQaTurns] = useState<QaTurn[]>([]);

  // object URLs for the uploaded keys (key A/B of each pair = keyUrls[i], keyUrls[i+1]).
  const keyUrls = useMemo(() => keys.files.map((f) => URL.createObjectURL(f)), [keys.files]);
  useEffect(() => () => keyUrls.forEach((u) => URL.revokeObjectURL(u)), [keyUrls]);

  // Effective key images for the review triptych. PNG upload → client object URLs. Drop-a-video
  // has no client files (keys are decoded server-side), so fall back to the server-served
  // key_urls from the result — otherwise the A/B cells render black.
  const effKeyUrls = useMemo(() => {
    if (keyUrls.length) return keyUrls;
    const sk = result?.key_urls;
    if (!sk) return keyUrls;
    const n = Object.keys(sk).length;
    return Array.from({ length: n }, (_, i) => sk[String(i)] ?? "");
  }, [keyUrls, result]);

  // Clear resets the whole review session (keys + log + results + verdicts + banner),
  // not just the loaded keyframes.
  const clearAll = () => {
    keys.clear();
    setLog([]);
    setResult(null);
    setVerdicts({});
    setBanner(null);
    setUpload(null);
    setQaTurns([]);
    setView("chat");
  };

  const run = async () => {
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setUpload({
      label: `${keys.files.length} keyframes · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"} · ${fps} fps`,
      thumbs: keyUrls.slice(0, 6),
    });
    setRunning(true);
    try {
      await runSession(keys.files, engines, fps, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => setResult(r),
        onError: (m) => setBanner(m),
      });
    } catch (err) {
      console.error("run session failed:", err);
      setBanner("Couldn't reach the co-pilot — is the service running? Press Run to retry.");
    }
    setRunning(false);
  };

  const runVideo = async () => {
    if (!videoFile) return;
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setUpload({
      label: `${videoFile.name} · stride ${stride} · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"}`,
      thumbs: [],
    });
    setRunning(true);
    try {
      await runVideoSession(videoFile, stride, fps, engines, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => setResult(r),
        onError: (m) => setBanner(m),
      });
    } catch (err) {
      console.error("run video session failed:", err);
      setBanner("Couldn't reach the co-pilot — is the service running? Press Run to retry.");
    }
    setRunning(false);
  };

  // draw-key loop: artist supplies a breakdown key for gap `index` → server targeted re-fill.
  // Insert the key at the SAME position client-side (no re-sort) so keyUrls stays index-aligned.
  const refillKey = async (index: number, file: File) => {
    const ref = result?.artifacts?.montage || result?.artifacts?.video;
    if (!ref) return;
    const sid = ref.split("/")[2];          // /session/{sid}/montage.png[?r=n]
    const fd = new FormData();
    fd.append("index", String(index));
    fd.append("key", file);
    try {
      const resp = await fetch(`/session/${sid}/key`, { method: "POST", body: fd });
      if (!resp.ok) { setBanner(`Add-key failed (server ${resp.status}) — re-run, or try a smaller PNG.`); return; }
      const d = await resp.json();
      keys.insertAt(index + 1, file);
      // a key inserted into gap `index` splits it and shifts every LATER pair by +1 — REMAP the
      // artist's verdicts (don't wipe: losing N accept/reject marks on one drawn key is brutal at scale).
      setVerdicts((prev) => {
        const next: Record<number, "accept" | "reject"> = {};
        for (const [k, v] of Object.entries(prev)) {
          const j = Number(k);
          if (j < index) next[j] = v;             // before the gap → unchanged
          else if (j > index) next[j + 1] = v;    // after the gap → shifted +1 (j === index was the needs_key gap, no verdict)
        }
        return next;
      });
      setLog(d.pairs);
      setResult(d.result);
    } catch (err) {
      console.error("add-key failed:", err);
      setBanner("Couldn't add your key — is the service running? Try again.");
    }
  };

  const buildDemo = async () => {
    setDemoBanner(null);
    setDemoResult(null);
    setDemoBuilding(true);
    try {
      setDemoResult(await runDemo(demo.files, engines, fps || "48"));
    } catch (err) {
      setDemoBanner(`${err}`);
    }
    setDemoBuilding(false);
  };

  // Clear resets the WHOLE demo panel — loaded frames AND the built comparison result/banner.
  // (demo.clear alone only empties files, leaving the wipe video on screen → "Clear does nothing".)
  const clearDemo = () => {
    demo.clear();
    setDemoResult(null);
    setDemoBanner(null);
  };

  // grounded session Q&A → POST /session/{sid}/ask (sid via the same artifact-URL
  // trick refillKey uses); the pending turn renders as a typing indicator.
  const onAsk = async (q: string) => {
    const ref = result?.artifacts?.montage || result?.artifacts?.video;
    const sid = ref ? ref.split("/")[2] : null;
    if (!sid) return;
    const n = qaTurns.length;
    setQaTurns((prev) => [...prev, { q, answer: null }]);
    try {
      const r = await askQuestion(sid, q);
      setQaTurns((prev) => prev.map((t, i) => (i === n ? { ...t, answer: r.answer, grounded: r.grounded } : t)));
    } catch {
      setQaTurns((prev) => prev.map((t, i) =>
        (i === n ? { ...t, answer: "Couldn't reach the assistant — is the service running? Try again.", grounded: false } : t)));
    }
  };

  const msgs = useMemo(
    () => deriveMessages({ upload, log, result, running, banner, qa: qaTurns }),
    [upload, log, result, running, banner, qaTurns],
  );
  const openBoard = (focus: number | null) => { setBoardFocus(focus); setView("board"); };

  return (
    <div className="app">
      {view === "chat" ? (
        <div className="chat-page">
          <header className="chat-brand">
            <PegBar />
            <div>
              <h1>In-Between Co-pilot</h1>
              <p className="tier">中割り douga · 作監 on-model QA</p>
            </div>
          </header>
          {!upload && log.length === 0 && !result && <MultiplaneHero />}
          <ChatView msgs={msgs} keyUrls={effKeyUrls} band={result?.csq}
            onOpenBoard={openBoard} onRefill={refillKey} onExport={downloadBundle} />
          <ChatComposer
            files={keys.files} fileUrls={keyUrls}
            onAdd={keys.add} onRemove={keys.remove}
            onClear={() => { clearAll(); setVideoFile(null); }}
            engines={engines} setEngines={setEngines}
            fps={fps} setFps={setFps}
            videoFile={videoFile} onVideo={setVideoFile}
            stride={stride} setStride={setStride}
            onRun={run} onRunVideo={runVideo} running={running}
            compact={running || log.length > 0}
            askEnabled={!!result?.artifacts} onAsk={onAsk}
          />
        </div>
      ) : (
        <>
          <div className="board-bar">
            <button type="button" className="btn btn-ghost" onClick={() => setView("chat")}>← Back to chat</button>
          </div>
          <ReviewWorkbench
            log={log}
            result={result}
            running={running}
            keyUrls={effKeyUrls}
            verdicts={verdicts}
            onVerdict={setVerdict}
            onRefill={refillKey}
            fps={Number(fps) || 24}
            initialFocus={boardFocus}
            compareSlot={
              <Compare
                files={demo.files}
                onAdd={demo.add}
                onClear={clearDemo}
                onBuild={buildDemo}
                building={demoBuilding}
                banner={demoBanner}
                result={demoResult}
              />
            }
          />
        </>
      )}
      {banner && <Toast key={banner} message={banner} onClose={() => setBanner(null)} />}
    </div>
  );
}
