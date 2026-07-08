// compare / demo panel: upload a full cut → side-by-side original-vs-RIFE reconstruction.
// Extracted from CopilotApp.tsx.
import { useState } from "react";
import type { DemoResult } from "../../types";
import { FilePicker } from "../input/FilePicker";
import { CompareWipe } from "./CompareWipe";

export interface CompareProps {
  files: File[];
  onAdd: (files: File[]) => void;
  onClear: () => void;
  onBuild: () => void;
  building: boolean;
  banner: string | null;
  result: DemoResult | null;
}

export function Compare(p: CompareProps) {
  const [open, setOpen] = useState(false);
  return (
    <section className="compare">
      <button
        type="button"
        className="compare-head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="eyebrow">Frame Comparison</span>
        <span className="compare-title">See it on a real cut</span>
        <span className="compare-toggle">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="compare-body">
          <p className="hint">
            Upload a <b>full cut</b> (every frame, named 0000.png, 0001.png…).
            The system drops every other frame, then RIFE reconstructs them —{" "}
            <b>left = source</b> · <b>right = RIFE</b>. Set <code>engine</code>{" "}
            + <code>fps</code> above.
          </p>
          <div className="controls">
            <FilePicker id="demokeys" label="Load full cut" onAdd={p.onAdd} />
            <button type="button" className="btn btn-quiet" onClick={p.onClear}>
              Clear
            </button>
            <button
              className="btn btn-primary"
              disabled={p.files.length < 3 || p.building}
              onClick={p.onBuild}
            >
              {p.building ? "Building…" : "Build comparison"}
            </button>
          </div>
          {p.files.length > 0 && (
            <div className="filelist">{p.files.length} frame(s) (full cut)</div>
          )}
          {p.banner && <div className="banner">{p.banner}</div>}
          {p.building && (
            <p className="filelist">
              building… (RIFE runs on the box; this can take a moment)
            </p>
          )}
          {p.result && (
            <>
              {p.result.video_orig && p.result.video_rife ? (
                <CompareWipe
                  orig={p.result.video_orig}
                  rife={p.result.video_rife}
                />
              ) : (
                <div className="screen">
                  <video src={p.result.video} controls />
                </div>
              )}
              <p className="filelist demo-summary">
                {p.result.frames} frames → {p.result.src} keys + {p.result.gt}{" "}
                GT · drag the divider · left source · right RIFE
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
