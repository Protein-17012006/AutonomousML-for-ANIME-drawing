// Bottom-docked composer — the ChatGPT-style "one place to interact":
// drop keys/video (= send a session), tweak args behind ⚙, ask follow-ups in text.
import { useState } from "react";
import { KeyframeDropzone } from "../input/KeyframeDropzone";
import { shortName } from "../../lib/shortName";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ChatComposer(p: {
  files: File[];
  fileUrls: string[];
  onAdd: (files: File[]) => void;
  onRemove: (f: File) => void;
  onClear: () => void;
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
  const sendQ = () => {
    const t = q.trim();
    if (!t) return;
    p.onAsk(t);
    setQ("");
  };
  return (
    <div className="chat-composer">
      {/* KEYFRAME DROP ZONE */}
      <KeyframeDropzone
        files={p.files}
        urls={p.fileUrls}
        onAdd={p.onAdd}
        onRemove={p.onRemove}
        onClear={p.onClear}
        compact={p.compact}
      />
      <div className="composer-row">
        {/* SETTING BUTTON */}
        <Button
          size={"icon"}
          type="button"
          className="btn btn-ghost gear"
          aria-expanded={gearOpen}
          onClick={() => setGearOpen((o) => !o)}
          title="run settings"
        >
          <Settings />
        </Button>
        {/* IF: SETTING IS ENABLED */}
        {gearOpen && (
          <div className="composer-settings">
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
            {/* STRIDE SELECTION (VIDEO) */}
            {p.videoFile && (
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
        {/* VIDEO INPUT */}
        <label
          className="btn btn-ghost composer-video"
          title={p.videoFile?.name ?? "or drop a whole video"}
        >
          {p.videoFile ? shortName(p.videoFile.name) : "🎬 video…"}
          <input
            type="file"
            accept="video/mp4,video/*"
            className="visually-hidden"
            onChange={(e) => {
              const f = e.currentTarget.files?.[0] ?? null;
              e.currentTarget.value = "";
              p.onVideo(f);
            }}
          />
        </label>
        {/* USER PROMPT INPUT */}
        <input
          className="ask-input"
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
        ) : // ELSE IF: VIDEO FILE PRESENTS
        p.videoFile ? (
          // BUTTON: RUNNING... (PROCESS IS RUNNING) || RUN VIDEO
          <button
            type="button"
            className="btn btn-primary"
            disabled={p.running}
            onClick={p.onRunVideo}
            title={p.videoFile.name}
          >
            {p.running ? "Running…" : "Run video"}
          </button>
        ) : (
          // ELSE: VIDEO FILE NOT PRESENTS (FRAMES)
          // BUTTON: RUNNING... (PROCESS IS RUNNING) || RUN
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
