// compare / demo panel: upload a full cut → side-by-side original-vs-RIFE reconstruction.
// Extracted from CopilotApp.tsx.
import { useState } from "react";
import type { DemoResult } from "../../types";
import { FilePicker } from "../input/FilePicker";
import { CompareWipe } from "./CompareWipe";
import { Button } from "@/components/ui/button";

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
      <Button
        variant="ghost"
        type="button"
        className="compare-head"
        aria-expanded={open}
        aria-controls="frame-comparison-body"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="eyebrow">Frame Comparison</span>
        <span className="compare-title">See it on a real cut</span>
        <span className="compare-toggle">{open ? "hide" : "show"}</span>
      </Button>
      {open && (
        <div id="frame-comparison-body" className="compare-body">
          <p className="hint">
            Upload a <b>full cut</b> (every frame, named 0000.png, 0001.png…).
            The system drops every other frame, then RIFE reconstructs them —{" "}
            <b>left = source</b> · <b>right = RIFE</b>. Set <code>engine</code> above.
          </p>
          <div className="controls">
            <FilePicker id="demokeys" label="Load full cut" onAdd={p.onAdd} />
            <Button type="button" variant="ghost" className="font-mono text-[12.5px] text-ash hover:text-washi" onClick={p.onClear}>
              Clear
            </Button>
            <Button
              className="border-ao bg-ao font-mono text-[12.5px] font-semibold tracking-[0.02em] text-on-ao hover:bg-ao/85"
              disabled={p.files.length < 3 || p.building}
              onClick={p.onBuild}
            >
              {p.building ? "Building…" : "Build comparison"}
            </Button>
          </div>
          {p.files.length > 0 && (
            <div className="col-span-full break-words font-mono text-xs text-ash [&_b]:font-bold [&_b]:text-washi">{p.files.length} frame(s) (full cut)</div>
          )}
          {p.banner && <div className="col-span-full rounded-md border border-line border-l-3 border-l-akaire-ink bg-sumi-3 px-3 py-[9px] font-mono text-[12.5px] text-washi">{p.banner}</div>}
          {p.building && (
            <p className="col-span-full break-words font-mono text-xs text-ash">
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
              <p className="col-span-full mt-2.5 break-words font-mono text-xs text-ash">
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
