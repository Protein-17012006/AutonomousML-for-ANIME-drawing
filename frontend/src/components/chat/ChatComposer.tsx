// Bottom-docked composer — the ChatGPT-style "one place to interact":
// drop keys/video (= send a session), tweak args behind ⚙, ask follow-ups in text.
import { useState } from "react";
import { KeyframeDropzone, shortName } from "../Inputs";

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
  compact: boolean;      // a session exists → fold the dropzone
  askEnabled: boolean;   // result retained server-side → grounded Q&A available
  onAsk: (q: string) => void;
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
      <KeyframeDropzone files={p.files} urls={p.fileUrls} onAdd={p.onAdd}
        onRemove={p.onRemove} onClear={p.onClear} compact={p.compact} />
      <div className="composer-row">
        <button type="button" className="btn btn-ghost gear" aria-expanded={gearOpen}
          onClick={() => setGearOpen((o) => !o)} title="run settings">⚙</button>
        {gearOpen && (
          <span className="composer-settings">
            <label className="field">
              engine
              <select value={p.engines} onChange={(e) => p.setEngines(e.target.value)}>
                <option value="box">Co-pilot (GPU)</option>
                <option value="stub">Demo (no GPU)</option>
              </select>
            </label>
            <label className="field">
              shoot rate
              <input type="number" min={1} max={60} step={1} value={p.fps}
                onChange={(e) => p.setFps(e.target.value)} />
            </label>
            {p.videoFile && (
              <label className="field">
                stride
                <input type="number" min={1} max={12} step={1} value={p.stride}
                  onChange={(e) => p.setStride(e.target.value)} />
              </label>
            )}
          </span>
        )}
        <label className="btn btn-ghost composer-video" title={p.videoFile?.name ?? "or drop a whole video"}>
          {p.videoFile ? shortName(p.videoFile.name) : "🎬 video…"}
          <input type="file" accept="video/mp4,video/*" className="visually-hidden"
            onChange={(e) => { const f = e.currentTarget.files?.[0] ?? null; e.currentTarget.value = ""; p.onVideo(f); }} />
        </label>
        <input
          className="ask-input"
          type="text"
          value={q}
          placeholder={p.askEnabled ? "Ask about this session — e.g. why was pair 3 flagged?"
            : "Run a session first, then ask me anything about it"}
          disabled={!p.askEnabled}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") sendQ(); }}
        />
        {p.askEnabled && q.trim() ? (
          <button type="button" className="btn btn-primary" onClick={sendQ}>Ask</button>
        ) : p.videoFile ? (
          <button type="button" className="btn btn-primary" disabled={p.running}
            onClick={p.onRunVideo} title={p.videoFile.name}>
            {p.running ? "Running…" : "Run video"}
          </button>
        ) : (
          <button type="button" className="btn btn-primary"
            disabled={p.files.length < 2 || p.running} onClick={p.onRun}>
            {p.running ? "Running…" : "Run"}
          </button>
        )}
      </div>
    </div>
  );
}
