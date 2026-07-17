// right-column per-pair frames. FrameTrip = the static key·in-between·key strip (or a big
// line-test on play); FrameCard wraps it as one reviewed pair (a mini multiplane rig,
// cursor-craned, carrying the hero's grammar). Extracted from CopilotApp.tsx.
import { useState } from "react";
import type { Explanation, PairEvent } from "../../types";
import { statusClass, statusGlyph } from "../../lib/pairView";
import { actionLabel, errTypeLabel, qaLabel } from "../../labels";
import { FlipPlayer, type Frame } from "./FlipPlayer";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/* eslint-disable @next/next/no-img-element -- review frames are dynamic session/object URLs. */

/* static key·in-between·key, or a big line-test on play */
function FrameTrip({
  p,
  a,
  b,
  mid,
  ex,
}: {
  p: PairEvent;
  a?: string;
  b?: string;
  mid?: string;
  ex?: Explanation;
}) {
  const [play, setPlay] = useState(false);
  const canPlay = !!(a && b);
  const frames: Frame[] =
    mid && a && b
      ? [
          { url: a, label: "key A" },
          { url: mid, label: "in-between" },
          { url: b, label: "key B" },
        ]
      : a && b
        ? [
            { url: a, label: "key A" },
            { url: b, label: "key B" },
          ]
        : [];
  return (
    <>
      <figcaption>
        <span className={`sglyph sglyph-${statusClass(p)}`} aria-hidden="true">
          {statusGlyph(p)}
        </span>
        pair {p.index} · {actionLabel(p.action)}
        {p.qa ? ` · ${qaLabel(p.qa)}` : ""}
        {canPlay && (
          <Button
            variant="link"
            type="button"
            className="ml-auto h-auto p-0 font-mono text-[11px] tracking-[0.04em] text-ao hover:bg-transparent hover:text-washi"
            onClick={(e) => {
              e.stopPropagation();
              setPlay((v) => !v);
            }}
          >
            {play ? "▦ frames" : "▶ play"}
          </Button>
        )}
      </figcaption>
      {play && frames.length >= 2 ? (
        <div className="trip-player">
          <FlipPlayer frames={frames} />
        </div>
      ) : (
        <div className="frametrip">
          {a ? (
            <img src={a} alt="key A" />
          ) : (
            <div className="fcell-empty">A</div>
          )}
          {mid ? (
            <div className="fcell-wrap">
              <img src={mid} alt="in-between" />
              {ex?.box && ex.box.length === 4 && (
                // the akaire correction box, with a 作監-style margin tag naming the defect,
                // tethered to the exact region so the frame, the place, and the why read as one note
                <span
                  className="region-box"
                  style={{
                    left: `${ex.box[0] * 100}%`,
                    top: `${ex.box[1] * 100}%`,
                    width: `${ex.box[2] * 100}%`,
                    height: `${ex.box[3] * 100}%`,
                  }}
                >
                  <span className="region-tag">
                    ✎ {errTypeLabel(ex.err_type)}
                  </span>
                </span>
              )}
            </div>
          ) : p.action === "needs_key" ? (
            <div className="fcell-draw">✎ draw a key here</div>
          ) : (
            <div className="fcell-empty">in-between</div>
          )}
          {b ? (
            <img src={b} alt="key B" />
          ) : (
            <div className="fcell-empty">B</div>
          )}
        </div>
      )}
    </>
  );
}

/* one reviewed pair as a mini multiplane rig (cursor-craned, carries the hero's grammar).
   On hover the three cells separate onto glass planes (the two keys recede, the co-pilot's
   in-between lifts forward + lit) and the rig cranes to the cursor. The thing under QA is
   physically presented forward — depth that does a job, not decoration. */
export function FrameCard({
  p,
  a,
  b,
  mid,
  ex,
  i,
  focused,
  onFocus,
}: {
  p: PairEvent;
  a?: string;
  b?: string;
  mid?: string;
  ex?: Explanation;
  i: number;
  focused: boolean;
  onFocus: () => void;
}) {
  return (
    <figure
      id={`frow-${p.index}`}
      data-pair={p.index}
      style={{ "--i": Math.min(i, 12) } as React.CSSProperties}
      className={cn("frameset", statusClass(p), focused && "focused")}
      role="button"
      tabIndex={0}
      onClick={onFocus}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onFocus();
        }
      }}
    >
      <FrameTrip p={p} a={a} b={b} mid={mid} ex={ex} />
    </figure>
  );
}
