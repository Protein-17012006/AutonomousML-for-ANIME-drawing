import type { Explanation, PairEvent } from "../../types";
import { statusClass } from "../../lib/pairView";
import { errTypeLabel } from "../../labels";
import { KeyframeUploadButton } from "./KeyframeUploadButton";
import { StatusGlyph } from "./StatusGlyph";
import { cn } from "@/lib/utils";
import { Pencil } from "lucide-react";

/* eslint-disable @next/next/no-img-element -- review frames are dynamic session/object URLs. */

function FrameTrip({
  p,
  a,
  b,
  mid,
  ex,
  onRefill,
  refillEnabled = true,
}: {
  p: PairEvent;
  a?: string;
  b?: string;
  mid?: string;
  ex?: Explanation;
  onRefill: (index: number, file: File) => void;
  refillEnabled?: boolean;
}) {
  return (
    <>
      <figcaption>
        <span className={`sglyph sglyph-${statusClass(p)}`} aria-hidden="true">
          <StatusGlyph pair={p} />
        </span>
        pair {p.index}
      </figcaption>

      <div className="frametrip">
          {a ? (
            <img src={a} alt="key A" />
          ) : (
            <div className="fcell-empty">A</div>
          )}

          {mid ? (
            <div className="fcell-wrap">
              <img src={mid} alt="in-between" />
              {/* //! REVIEW: ERROR BOX CURRENTLY NOT IN USE */}
              {ex?.box && ex.box.length === 4 && (
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
                    <Pencil className="mr-1 inline size-3" aria-hidden="true" />
                    {errTypeLabel(ex.err_type)}
                  </span>
                </span>
              )}
            </div>
          ) : p.action === "needs_key" ? (
            <div className="fcell-draw">
              {/* //! REDESIGN: IMPORT KEYFRAMEUPLOAD COMPONENT INTO THIS ONE, MAKE THIS ONE IMPORTABLE (your change) */}
              <KeyframeUploadButton
                disabled={!refillEnabled}
                className="w-full justify-center pt-0"
                buttonClassName="h-auto w-full border-0 bg-transparent px-0 py-0 uppercase hover:bg-transparent hover:text-akaire-ink"
                label="Draw a key here"
                onFileSelect={(file) => onRefill(p.index, file)}
              />
            </div>
          ) : (
            <div className="fcell-empty">in-between</div>
          )}

          {b ? (
            <img src={b} alt="key B" />
          ) : (
            <div className="fcell-empty">B</div>
          )}
      </div>
    </>
  );
}

export function FrameCard({
  p,
  a,
  b,
  mid,
  ex,
  i,
  focused,
  onFocus,
  onRefill,
  refillEnabled,
  pendingKeyUrl,
}: {
  p: PairEvent;
  a?: string;
  b?: string;
  mid?: string;
  ex?: Explanation;
  i: number;
  focused: boolean;
  onFocus: () => void;
  onRefill: (index: number, file: File) => void;
  refillEnabled?: boolean;
  pendingKeyUrl?: string;
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
      <FrameTrip p={p} a={a} b={b} mid={mid ?? pendingKeyUrl} ex={ex} onRefill={onRefill} refillEnabled={refillEnabled} />
    </figure>
  );
}
