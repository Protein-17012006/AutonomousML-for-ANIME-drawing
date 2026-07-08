// Bottom-docked composer — the ChatGPT-style "one place to interact":
// drop keys/video (= send a session), tweak args behind ⚙, ask follow-ups in text.
import { useState } from "react";
import { KeyframeDropzone } from "../input/KeyframeDropzone";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { InputMode } from "../../types";

export function ChatComposer(p: {
  files: File[];
  fileUrls: string[];
  onAdd: (files: File[]) => void;
  onRemove: (f: File) => void;
  onClear: () => void;
  onClearFrames: () => void; // frames-only clear (mode switch) — does NOT reset the session
  engines: string;
  setEngines: (s: string) => void;
  fps: string;
  setFps: (s: string) => void;
  videoFile: File | null;
  onVideo: (f: File | null) => void;
  stride: string;
  setStride: (s: string) => void;
  onRun: () => void;
  onRunVideo: () => void;
  running: boolean;
  compact: boolean; // a session exists → fold the dropzone
  askEnabled: boolean; // result retained server-side → grounded Q&A available
  onAsk: (q: string) => void;
  plantedCases: { id: string; title: string }[]; // labeled planted-error demo cases
  onRunPlanted: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [gearOpen, setGearOpen] = useState(false);
  const [mode, setMode] = useState<InputMode>("frames");
  // switching input mode stages exactly one path: drop whatever the other mode had loaded
  const changeMode = (next: InputMode) => {
    if (next === mode) return;
    if (next === "video") p.onClearFrames();
    else p.onVideo(null);
    setMode(next);
  };
  const sendQ = () => {
    const t = q.trim();
    if (!t) return;
    p.onAsk(t);
    setQ("");
  };
  return (
    <div className="flex flex-none flex-col gap-2 sticky bottom-0 border-t border-line bg-sumi pt-2.5 pb-3.5">
      {/* KEYFRAME / VIDEO DROP ZONE — the mode selector lives in its header */}
      <KeyframeDropzone
        files={p.files}
        urls={p.fileUrls}
        onAdd={p.onAdd}
        onRemove={p.onRemove}
        onClear={p.onClear}
        compact={p.compact}
        mode={mode}
        onModeChange={changeMode}
        videoFile={p.videoFile}
        onVideo={p.onVideo}
      />
      {/* IF: SETTING IS ENABLED — in-flow panel: below the dropzone, above the input row */}
      {gearOpen && (
        <div
          id="composer-settings-panel"
          className="flex w-full flex-wrap items-center gap-2 rounded-lg border border-line bg-sumi-2 p-3"
        >
          {/* ENGINE SELECTION */}
          <label className="field">
            engine
            <select
              value={p.engines}
              onChange={(e) => p.setEngines(e.target.value)}
            >
              <option value="box">Co-pilot (GPU)</option>
              <option value="stub">Demo (no GPU)</option>
            </select>
          </label>
          {/* FPS SELECTION */}
          <label className="field">
            shoot rate
            <input
              type="number"
              min={1}
              max={60}
              step={1}
              value={p.fps}
              onChange={(e) => p.setFps(e.target.value)}
            />
          </label>
          {/* STRIDE SELECTION (VIDEO ONLY) */}
          {mode === "video" && (
            <label className="field">
              stride
              <input
                type="number"
                min={1}
                max={12}
                step={1}
                value={p.stride}
                onChange={(e) => p.setStride(e.target.value)}
              />
            </label>
          )}
          {/* PLANTED CASE TO TEST QA AGENT */}
          {p.plantedCases.length > 0 && (
            <label className="field">
              🧪 planted demo
              <select
                value=""
                disabled={p.running}
                onChange={(e) => {
                  const id = e.target.value;
                  if (id) p.onRunPlanted(id);
                }}
              >
                <option value="">Select a QA demo options</option>
                {p.plantedCases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {/* SETTING BUTTON */}
        <Button
          size={"icon"}
          type="button"
          className="btn btn-ghost"
          aria-expanded={gearOpen}
          aria-controls="composer-settings-panel"
          onClick={() => setGearOpen((o) => !o)}
          title="run settings"
        >
          <Settings />
        </Button>
        {/* USER PROMPT INPUT */}
        <input
          className="flex-1 min-w-[180px] rounded-full border border-line bg-sumi-3 px-3.5 py-[9px] font-body text-[0.86rem] text-washi focus:outline-2 focus:outline-offset-1 focus:outline-ao disabled:opacity-[0.55]"
          type="text"
          value={q}
          placeholder={
            p.askEnabled
              ? "Ask about this session — e.g. why was pair 3 flagged?"
              : "Run a session first, then ask me anything about it"
          }
          disabled={!p.askEnabled}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") sendQ();
          }}
        />
        {/* IF ASKED IS ALLOWED && THERE IS USER PROMPT */}
        {p.askEnabled && q.trim() ? (
          // BUTTON: ASK
          <button type="button" className="btn btn-primary" onClick={sendQ}>
            Ask
          </button>
        ) : mode === "video" ? (
          // BUTTON: RUNNING… (PROCESS IS RUNNING) || RUN VIDEO
          <button
            type="button"
            className="btn btn-primary"
            disabled={!p.videoFile || p.running}
            onClick={p.onRunVideo}
            title={p.videoFile?.name}
          >
            {p.running ? "Running…" : "Run video"}
          </button>
        ) : (
          // ELSE: FRAMES MODE — RUN (needs 2+ keys)
          <button
            type="button"
            className="btn btn-primary"
            disabled={p.files.length < 2 || p.running}
            onClick={p.onRun}
          >
            {p.running ? "Running…" : "Run"}
          </button>
        )}
      </div>
    </div>
  );
}
