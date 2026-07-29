// reconstructed-cut transport: X-sheet rail + frame-accurate step (rVFC).
// Extracted from CopilotApp.tsx.
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";

type VideoWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (
    cb: (now: number, metadata: { mediaTime: number }) => void,
  ) => number;

  cancelVideoFrameCallback?: (handle: number) => void;
};

export function ReconPlayer({ src, fps }: { src: string; fps: number }) {
  const vref = useRef<HTMLVideoElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0); // currentTime (s)
  const [dur, setDur] = useState(0); // duration (s)

  // frame-accurate playhead via requestVideoFrameCallback; fallback to timeupdate
  useEffect(() => {
    const v = vref.current as VideoWithFrameCallback | null;
    if (!v) return;

    if (v.requestVideoFrameCallback) {
      let h = 0;

      const cb = (_n: number, m: { mediaTime: number }) => {
        setT(m.mediaTime);
        h = v.requestVideoFrameCallback!(cb);
      };
      h = v.requestVideoFrameCallback(cb);

      return () => {
        try {
          v.cancelVideoFrameCallback?.(h);
        } catch {}
      };
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
    if (v.paused) void v.play();
    else v.pause();
  };
// Step frame
  const step = (d: number) => {
    const v = vref.current;
    if (!v) return;
    v.pause();
    v.currentTime = Math.max(
      0,
      Math.min(dur || 0, (Math.round(t * fps) + d) / fps + 1e-4),
    );
  };
// Rail
  const seek = (clientX: number) => {
    const v = vref.current;
    const el = railRef.current;
    if (!v || !el || !dur) return;
    const r = el.getBoundingClientRect();
    v.currentTime =
      Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * dur;
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
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="font-mono text-[11px] text-washi hover:border-ao hover:bg-sumi-2 hover:text-ao active:translate-y-px"
          onClick={() => step(-1)}
          aria-label="previous frame"
        >
          <ChevronLeft className="size-3.5" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-w-9 font-mono text-[11px] text-washi hover:border-ao hover:bg-sumi-2 hover:text-ao active:translate-y-px"
          onClick={toggle}
          aria-label={playing ? "pause" : "play"}
        >
          {playing ? (
            <Pause className="size-3.5" aria-hidden="true" />
          ) : (
            <Play className="size-3.5" aria-hidden="true" />
          )}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="font-mono text-[11px] text-washi hover:border-ao hover:bg-sumi-2 hover:text-ao active:translate-y-px"
          onClick={() => step(1)}
          aria-label="next frame"
        >
          <ChevronRight className="size-3.5" aria-hidden="true" />
        </Button>
        <div
          className="rplayer-rail"
          ref={railRef}
          role="slider"
          aria-label="scrub the reconstructed cut"
          aria-valuenow={frame}
          aria-valuemin={0}
          aria-valuemax={total}
          tabIndex={0}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            seek(e.clientX);
          }}
          onPointerMove={(e) => {
            if (e.buttons) seek(e.clientX);
          }}
          onPointerUp={(e) => {
            e.currentTarget.releasePointerCapture?.(e.pointerId);
          }}
          onPointerCancel={(e) => {
            e.currentTarget.releasePointerCapture?.(e.pointerId);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") {
              e.preventDefault();
              step(-1);
            } else if (e.key === "ArrowRight") {
              e.preventDefault();
              step(1);
            }
          }}
        >
          <span className="rplayer-fill" style={{ width: `${pct}%` }} />
          <span className="rplayer-head" style={{ left: `${pct}%` }} />
        </div>
        <span className="rplayer-count">
          {String(frame).padStart(3, "0")}
          <i>/{total}</i>
        </span>
      </div>
    </div>
  );
}
