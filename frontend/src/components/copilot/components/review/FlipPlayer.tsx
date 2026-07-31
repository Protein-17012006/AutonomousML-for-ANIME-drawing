// per-pair line-test (flip key_A → in-between → key_B). Extracted from CopilotApp.tsx.
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";

/* eslint-disable @next/next/no-img-element -- review frames are dynamic session/object URLs. */

export type Frame = { url: string; label: string };

export function FlipPlayer({ frames }: { frames: Frame[] }) {
  const [playing, setPlaying] = useState(true);
  const [i, setI] = useState(0);

  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const id = setInterval(() => setI((k) => k + 1), 240); // shoot-on-2s line-test cadence
    return () => clearInterval(id);
  }, [frames.length, playing]);

  const pos = ((i % frames.length) + frames.length) % frames.length;
  const cur = pos;
  const step = (d: number) => {
    setPlaying(false);
    setI((k) => k + d);
  };
  return (
    <div className="flip">
      <div className="flip-stage">
        {frames.map((f, k) => (
          <img
            key={k}
            src={f.url}
            alt={f.label}
            className={k === cur ? "on" : ""}
            draggable={false}
          />
        ))}
        <span className="flip-tag">{frames[cur]?.label}</span>
        <span className="flip-count">
          {pos + 1}/{frames.length}
        </span>
      </div>

      <div className="flip-ctl">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="font-mono text-xs text-washi hover:border-ao hover:bg-sumi-3 hover:text-ao active:translate-y-px"
          onClick={() => step(-1)}
          aria-label="previous frame"
        >
          <ChevronLeft className="size-3.5" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="font-mono text-xs text-washi hover:border-ao hover:bg-sumi-3 hover:text-ao active:translate-y-px"
          onClick={() => setPlaying((pl) => !pl)}
        >
          {playing ? (
            <>
              <Pause className="size-3.5" aria-hidden="true" /> Pause
            </>
          ) : (
            <>
              <Play className="size-3.5" aria-hidden="true" /> Play
            </>
          )}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="font-mono text-xs text-washi hover:border-ao hover:bg-sumi-3 hover:text-ao active:translate-y-px"
          onClick={() => step(1)}
          aria-label="next frame"
        >
          <ChevronRight className="size-3.5" aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
