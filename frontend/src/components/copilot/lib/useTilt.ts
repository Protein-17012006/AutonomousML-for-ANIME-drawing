// multiplane camera tilt hook — the rig cranes to the cursor for real parallax.
// Pointer-only and reduced-motion-safe (the rig rests when there's no fine pointer or
// the user prefers reduced motion). Extracted from CopilotApp.tsx.
import { useEffect, useRef } from "react";

export function useTilt<T extends HTMLElement = HTMLDivElement>() {
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
