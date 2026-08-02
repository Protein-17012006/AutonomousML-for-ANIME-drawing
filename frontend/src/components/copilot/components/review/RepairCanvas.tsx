// Repair canvas: the artist paints the region that is wrong, and only that.
//
// The stroke semantics are Long's, from the GIMM Studio repair surface on the
// box: white strokes on transparency, erase via destination-out, and a mask
// committed as a PNG whose ALPHA channel carries the stroke. The service reads
// that alpha at the same `> 8` threshold, so a half-transparent smudge is not a
// selection.
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Eraser, Paintbrush, RotateCcw } from "lucide-react";

type Mode = "paint" | "erase";

export function RepairCanvas({
  frameUrl,
  disabled,
  onSubmit,
  onCancel,
}: {
  frameUrl: string;
  disabled?: boolean;
  onSubmit: (maskPng: string) => void;
  onCancel: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [mode, setMode] = useState<Mode>("paint");
  const [brush, setBrush] = useState(24);
  const [painted, setPainted] = useState(false);
  const [ready, setReady] = useState(false);

  // The mask must be at the frame's own pixel size: the service resizes with
  // NEAREST, so a canvas sized to the CSS box would quantise the artist's edge.
  useEffect(() => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext("2d");
      context?.clearRect(0, 0, canvas.width, canvas.height);
      imageRef.current = image;
      setPainted(false);
      setReady(true);
    };
    image.src = frameUrl;
    return () => {
      image.onload = null;
      setReady(false);
    };
  }, [frameUrl]);

  function pointAt(event: React.PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current!;
    const box = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - box.left) / box.width) * canvas.width,
      y: ((event.clientY - box.top) / box.height) * canvas.height,
    };
  }

  function stroke(from: { x: number; y: number }, to: { x: number; y: number }) {
    const context = canvasRef.current?.getContext("2d");
    if (!context) return;
    context.globalCompositeOperation =
      mode === "erase" ? "destination-out" : "source-over";
    context.strokeStyle = "#ffffff";
    context.lineWidth = brush;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    if (disabled || !ready) return;
    // Capture on the element, so a stroke that leaves the canvas mid-drag still
    // ends cleanly instead of leaving the surface stuck in a drawing state.
    event.currentTarget.setPointerCapture(event.pointerId);
    drawing.current = true;
    const point = pointAt(event);
    last.current = point;
    stroke(point, point);
    setPainted(true);
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current || !last.current) return;
    const point = pointAt(event);
    stroke(last.current, point);
    last.current = point;
  }

  function endStroke(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    drawing.current = false;
    last.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function clear() {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    setPainted(false);
  }

  /** Whether any pixel is opaque enough to count, at the service's threshold. */
  function maskHasPixels(): boolean {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return false;
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 3; index < data.length; index += 4) {
      if (data[index] > 8) return true;
    }
    return false;
  }

  function submit() {
    // Erasing back to nothing leaves `painted` true, so ask the pixels, not the
    // flag: submitting an empty mask would spend a GPU slot to be refused.
    if (!maskHasPixels()) {
      setPainted(false);
      return;
    }
    onSubmit(canvasRef.current!.toDataURL("image/png"));
  }

  return (
    <div className="repair-canvas">
      <div className="repair-canvas-toolbar review-subfilters" role="toolbar">
        <Button
          variant="ghost"
          type="button"
          aria-pressed={mode === "paint"}
          className={cn(mode === "paint" && "is-active")}
          onClick={() => setMode("paint")}
        >
          <Paintbrush aria-hidden /> Paint
        </Button>
        <Button
          variant="ghost"
          type="button"
          aria-pressed={mode === "erase"}
          className={cn(mode === "erase" && "is-active")}
          onClick={() => setMode("erase")}
        >
          <Eraser aria-hidden /> Erase
        </Button>
        <label className="repair-brush">
          Brush
          <input
            type="range"
            min={4}
            max={96}
            step={2}
            value={brush}
            onChange={(event) => setBrush(Number(event.target.value))}
          />
        </label>
        <Button variant="ghost" type="button" onClick={clear}>
          <RotateCcw aria-hidden /> Clear
        </Button>
      </div>

      <div className="repair-canvas-stage">
        <img src={frameUrl} alt="" className="repair-canvas-frame" />
        <canvas
          ref={canvasRef}
          className="repair-canvas-paint"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endStroke}
          onPointerCancel={endStroke}
        />
      </div>

      <p className="repair-canvas-hint">
        Mark only the region that is wrong. The frames either side of it are sent
        as context, so the repair follows the motion already in the cut.
      </p>

      <div className="repair-canvas-actions">
        <Button variant="ghost" type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" disabled={disabled || !painted} onClick={submit}>
          Repair this frame
        </Button>
      </div>
    </div>
  );
}
