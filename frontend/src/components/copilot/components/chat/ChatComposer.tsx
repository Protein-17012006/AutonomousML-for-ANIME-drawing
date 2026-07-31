// Bottom-docked composer — the ChatGPT-style "one place to interact":
// drop keys/video (= send a session), tweak args behind ⚙, ask follow-ups in text.
import { useState } from "react";
import { KeyframeDropzone } from "../input/KeyframeDropzone";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Field, FieldLabel } from "@/components/ui/field";
import type { InputMode } from "../../types";

const primaryButtonClass =
  "rounded-md border border-ao bg-ao px-[15px] py-2 font-mono text-[12.5px] font-semibold tracking-[0.02em] text-on-ao transition-all hover:-translate-y-px hover:bg-ao/85 hover:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-ao)_26%,transparent),0_5px_16px_color-mix(in_oklab,var(--color-ao)_30%,transparent)] active:translate-y-px disabled:cursor-not-allowed disabled:border-line disabled:bg-sumi-3 disabled:text-ash";

export function ChatComposer(p: {
  files: File[];
  fileUrls: string[];
  onAdd: (files: File[]) => void;
  onRemove: (f: File) => void;
  onClear: () => void;
  engines: string;
  setEngines: (s: string) => void;
  interpolator: string;
  setInterpolator: (s: string) => void;
  cadence: string;
  setCadence: (s: string) => void;
  smoothness: string;
  setSmoothness: (s: string) => void;
  videoFile: File | null;
  onVideo: (f: File | null) => void;
  mode: InputMode; // lifted to CopilotApp so ChatWelcome's quick-import can drive it too
  onModeChange: (m: InputMode) => void;
  stride: string;
  setStride: (s: string) => void;
  onRun: () => void;
  onRunVideo: () => void;
  running: boolean;
  compact: boolean; // a session exists → fold the dropzone
  askEnabled: boolean; // result retained server-side → grounded Q&A available
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
    <div className="flex flex-none flex-col gap-2 sticky bottom-0 border-t border-line bg-sumi pt-2.5 pb-3.5">
      {/* KEYFRAME / VIDEO DROP ZONE — the mode selector lives in its header */}
      <KeyframeDropzone
        files={p.files}
        urls={p.fileUrls}
        onAdd={p.onAdd}
        onRemove={p.onRemove}
        onClear={p.onClear}
        compact={p.compact}
        mode={p.mode}
        onModeChange={p.onModeChange}
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
          <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
            <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">engine</FieldLabel>
            <Select value={p.engines} onValueChange={p.setEngines}>
              <SelectTrigger size="sm" className="w-auto font-mono text-[13px] text-washi">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="box">Co-pilot (GPU)</SelectItem>
                <SelectItem value="stub">Local stub (no GPU)</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {/* INTERPOLATION MODEL SELECTION */}
          <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
            <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">model</FieldLabel>
            <Select
              value={p.interpolator}
              onValueChange={p.setInterpolator}
              disabled={p.engines !== "box"}
            >
              <SelectTrigger size="sm" className="w-auto font-mono text-[13px] text-washi">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="rife">RIFE</SelectItem>
                <SelectItem value="gimm">GIMM-VFI</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {/* CADENCE SELECTION — shoot-on-Ns rate the keys were drawn at */}
          <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
            <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">cadence</FieldLabel>
            <Select value={p.cadence} onValueChange={p.setCadence}>
              <SelectTrigger size="sm" className="w-auto font-mono text-[13px] text-washi">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="24">on-1s</SelectItem>
                <SelectItem value="12">on-2s</SelectItem>
                <SelectItem value="8">on-3s</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {/* SMOOTHNESS SELECTION — in-between multiplier on top of the cadence */}
          <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
            <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">smoothness</FieldLabel>
            <Select value={p.smoothness} onValueChange={p.setSmoothness}>
              <SelectTrigger size="sm" className="w-auto font-mono text-[13px] text-washi">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Off</SelectItem>
                <SelectItem value="2">Standard</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {/* STRIDE SELECTION (VIDEO ONLY) */}
          {p.mode === "video" && (
            <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
              <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">stride</FieldLabel>
              <Input
                type="number"
                min={1}
                max={12}
                step={1}
                className="h-7 w-14 rounded-md border-line bg-sumi-3 px-2 py-1.5 font-mono text-[13px] text-washi"
                value={p.stride}
                onChange={(e) => p.setStride(e.target.value)}
              />
            </Field>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {/* SETTING BUTTON */}
        <Button
          size="icon"
          variant="ghost"
          type="button"
          aria-expanded={gearOpen}
          aria-controls="composer-settings-panel"
          onClick={() => setGearOpen((o) => !o)}
          title="Run settings"
        >
          <Settings />
        </Button>
        {/* USER PROMPT INPUT */}
        <label htmlFor="session-question" className="sr-only">
          Ask about this session
        </label>
        <Input
          id="session-question"
          className="min-w-[180px] flex-1 rounded-full border-line bg-sumi-3 px-3.5 py-[9px] font-body text-[0.86rem] text-washi focus-visible:border-ao focus-visible:ring-ao disabled:opacity-[0.55]"
          type="text"
          value={q}
          placeholder={
            p.askEnabled
              ? "Ask about this session — e.g. why was pair 3 flagged?"
              : "Run a session to ask about its decisions"
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
          <Button type="button" className={primaryButtonClass} onClick={sendQ}>
            Ask
          </Button>
        ) : p.mode === "video" ? (
          // BUTTON: RUNNING… (PROCESS IS RUNNING) || RUN VIDEO
          <Button
            type="button"
            className={primaryButtonClass}
            disabled={!p.videoFile || p.running}
            onClick={p.onRunVideo}
            title={p.videoFile?.name}
          >
            {p.running ? "Running…" : "Run video"}
          </Button>
        ) : (
          // ELSE: FRAMES MODE — RUN (needs 2+ keys)
          <Button
            type="button"
            className={primaryButtonClass}
            disabled={p.files.length < 2 || p.running}
            onClick={p.onRun}
          >
            {p.running ? "Running…" : "Run"}
          </Button>
        )}
      </div>
    </div>
  );
}
