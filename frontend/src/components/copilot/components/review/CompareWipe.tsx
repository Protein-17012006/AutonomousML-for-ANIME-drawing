// before/after wipe: drag SOURCE↔RIFE through the SAME frame (clip-path inset).
// Extracted from CopilotApp.tsx.
import { useEffect, useRef, useState } from "react";

export function CompareWipe({ orig, rife }: { orig: string; rife: string }) {
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
      onPointerDown={(e) => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); moveTo(e.clientX); }}
      onPointerMove={(e) => { if (dragging.current) moveTo(e.clientX); }}
      onPointerUp={(e) => { dragging.current = false; e.currentTarget.releasePointerCapture?.(e.pointerId); }}
      onPointerCancel={() => { dragging.current = false; }}
      onPointerLeave={() => { dragging.current = false; }}
    >
      <video ref={aRef} className="cmpwipe-a" src={orig} autoPlay muted loop playsInline />
      <video ref={bRef} className="cmpwipe-b" src={rife} autoPlay muted loop playsInline />
      <span className="cmpwipe-tag cmpwipe-tag-l">SOURCE KEYFRAMES</span>
      <span className="cmpwipe-tag cmpwipe-tag-r">RIFE Interpolation</span>
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
