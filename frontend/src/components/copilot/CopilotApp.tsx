"use client";
// Co-pilot app shell — owns all session state and switches the chat ⇄ board surfaces.
// The presentational pieces were split out into ./components/* and the logic into ./lib/*
// (this file used to be a ~1360-line monolith holding all of them).
import { useEffect, useMemo, useState } from "react";
import type { PairEvent, ResultEvent, DemoResult, InputMode } from "./types";
import {
  runSession,
  runDemo,
  runVideoSession,
  runPlantedSession,
  fetchPlantedCases,
  askQuestion,
  type PlantedCase,
} from "./api";
import { deriveMessages, type QaTurn, type UserTurn } from "./lib/chatModel";
import { useFileSet } from "./lib/useFileSet";
import { downloadBundle } from "./lib/exportSession";
import { ChatHeader } from "./components/chat/ChatHeader";
import { ChatView } from "./components/chat/ChatView";
import { ChatComposer } from "./components/chat/ChatComposer";
import { ChatWelcome } from "./components/chat/ChatWelcome";
import { ReviewWorkbench } from "./components/review/ReviewWorkbench";
import { Compare } from "./components/review/Compare";
import { Toast } from "./components/review/Toast";

export default function App() {
  const keys = useFileSet();
  const demo = useFileSet();
  const [engines, setEngines] = useState("box");
  const [fps, setFps] = useState("24");
  // Planted-error demo cases (labeled): loaded once; empty when the server predates the feature.
  const [plantedCases, setPlantedCases] = useState<PlantedCase[]>([]);
  useEffect(() => {
    fetchPlantedCases()
      .then(setPlantedCases)
      .catch(() => {});
  }, []);

  const [running, setRunning] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [log, setLog] = useState<PairEvent[]>([]);
  const [result, setResult] = useState<ResultEvent | null>(null);
  const [verdicts, setVerdicts] = useState<Record<number, "accept" | "reject">>(
    {},
  );
  const setVerdict = (idx: number, v: "accept" | "reject") =>
    setVerdicts((prev) => {
      const n = { ...prev };
      if (n[idx] === v)
        delete n[idx]; // toggle off
      else n[idx] = v;
      return n;
    });

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [stride, setStride] = useState("2");
  // Composer input mode, lifted here (was in ChatComposer) so BOTH the dropzone and the
  // ChatWelcome quick-import buttons share one source of truth.
  const [mode, setMode] = useState<InputMode>("frames");

  const [demoBuilding, setDemoBuilding] = useState(false);
  const [demoBanner, setDemoBanner] = useState<string | null>(null);
  const [demoResult, setDemoResult] = useState<DemoResult | null>(null);

  // chat-first surface state (vault 'Chat-First Copilot Surface')
  const [view, setView] = useState<"chat" | "board">("chat");
  const [boardFocus, setBoardFocus] = useState<number | null>(null);
  const [upload, setUpload] = useState<UserTurn | null>(null);
  const [qaTurns, setQaTurns] = useState<QaTurn[]>([]);

  // object URLs for the uploaded keys (key A/B of each pair = keyUrls[i], keyUrls[i+1]).
  const keyUrls = useMemo(
    () => keys.files.map((f) => URL.createObjectURL(f)),
    [keys.files],
  );
  useEffect(
    () => () => keyUrls.forEach((u) => URL.revokeObjectURL(u)),
    [keyUrls],
  );

  // Effective key images for the review triptych. PNG upload → client object URLs. Drop-a-video
  // has no client files (keys are decoded server-side), so fall back to the server-served
  // key_urls from the result — otherwise the A/B cells render black.
  const effKeyUrls = useMemo(() => {
    if (keyUrls.length) return keyUrls;
    const sk = result?.key_urls;
    if (!sk) return keyUrls;
    const n = Object.keys(sk).length;
    return Array.from({ length: n }, (_, i) => sk[String(i)] ?? "");
  }, [keyUrls, result]);

  // Clear resets the whole review session (keys + log + results + verdicts + banner),
  // not just the loaded keyframes.
  const clearAll = () => {
    keys.clear();
    setLog([]);
    setResult(null);
    setVerdicts({});
    setBanner(null);
    setUpload(null);
    setQaTurns([]);
    setView("chat");
  };

  // Switching input mode drops whatever the OTHER mode had staged, so `files` and `videoFile`
  // are never both non-empty (keeps the review triptych's client-vs-server key fallback correct).
  const changeMode = (next: InputMode) => {
    if (next === mode) return;
    if (next === "video")
      keys.clear(); // leaving frames → drop staged keys
    else setVideoFile(null); // leaving video → drop staged clip
    setMode(next);
  };
  // ChatWelcome quick-import → feed the SAME state the dropzone reads, and flip the mode to
  // match the imported media (so the dropzone selector + preview update in lockstep).
  const importFrames = (picked: File[]) => {
    if (!picked.length) return;
    changeMode("frames");
    keys.add(picked);
  };
  const importVideo = (file: File) => {
    changeMode("video");
    setVideoFile(file);
  };

  const run = async () => {
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setUpload({
      label: `${keys.files.length} keyframes · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"} · ${fps} fps`,
      thumbs: keyUrls.slice(0, 6),
    });
    setRunning(true);
    try {
      await runSession(keys.files, engines, fps, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => setResult(r),
        onError: (m) => setBanner(m),
      });
    } catch (err) {
      console.error("run session failed:", err);
      setBanner(
        "Couldn't reach the co-pilot — is the service running? Press Run to retry.",
      );
    }
    setRunning(false);
  };

  // Planted-error DEMO run: the server plants a stored bad in-between from a frozen suite
  // and the real QA/annotate path judges it. Clearly labeled — the live gate produces no
  // natural flags (that refusal is the product story; this shows the flag surface anyway).
  const runPlanted = async (caseId: string) => {
    const c = plantedCases.find((x) => x.id === caseId);
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setUpload({
      label: `🧪 PLANTED DEMO · ${c?.title ?? caseId} — lỗi được cấy chủ đích để trình diễn QA`,
      thumbs: [],
    });
    setRunning(true);
    try {
      await runPlantedSession(caseId, engines, fps, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => setResult(r),
        onError: (m) => setBanner(m),
      });
    } catch (err) {
      console.error("planted session failed:", err);
      setBanner("Couldn't reach the co-pilot — is the service running?");
    }
    setRunning(false);
  };

  const runVideo = async () => {
    if (!videoFile) return;
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setUpload({
      label: `${videoFile.name} · stride ${stride} · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"}`,
      thumbs: [],
    });
    setRunning(true);
    try {
      await runVideoSession(videoFile, stride, fps, engines, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => setResult(r),
        onError: (m) => setBanner(m),
      });
    } catch (err) {
      console.error("run video session failed:", err);
      setBanner(
        "Couldn't reach the co-pilot — is the service running? Press Run to retry.",
      );
    }
    setRunning(false);
  };

  // draw-key loop: artist supplies a breakdown key for gap `index` → server targeted re-fill.
  // Insert the key at the SAME position client-side (no re-sort) so keyUrls stays index-aligned.
  const refillKey = async (index: number, file: File) => {
    const ref = result?.artifacts?.montage || result?.artifacts?.video;
    if (!ref) return;
    const sid = ref.split("/")[2]; // /session/{sid}/montage.png[?r=n]
    const fd = new FormData();
    fd.append("index", String(index));
    fd.append("key", file);
    try {
      const resp = await fetch(`/session/${sid}/key`, {
        method: "POST",
        body: fd,
      });
      if (!resp.ok) {
        setBanner(
          `Add-key failed (server ${resp.status}) — re-run, or try a smaller PNG.`,
        );
        return;
      }
      const d = await resp.json();
      keys.insertAt(index + 1, file);
      // a key inserted into gap `index` splits it and shifts every LATER pair by +1 — REMAP the
      // artist's verdicts (don't wipe: losing N accept/reject marks on one drawn key is brutal at scale).
      setVerdicts((prev) => {
        const next: Record<number, "accept" | "reject"> = {};
        for (const [k, v] of Object.entries(prev)) {
          const j = Number(k);
          if (j < index)
            next[j] = v; // before the gap → unchanged
          else if (j > index) next[j + 1] = v; // after the gap → shifted +1 (j === index was the needs_key gap, no verdict)
        }
        return next;
      });
      setLog(d.pairs);
      setResult(d.result);
    } catch (err) {
      console.error("add-key failed:", err);
      setBanner("Couldn't add your key — is the service running? Try again.");
    }
  };

  const buildDemo = async () => {
    setDemoBanner(null);
    setDemoResult(null);
    setDemoBuilding(true);
    try {
      setDemoResult(await runDemo(demo.files, engines, fps || "48"));
    } catch (err) {
      setDemoBanner(`${err}`);
    }
    setDemoBuilding(false);
  };

  // Clear resets the WHOLE demo panel — loaded frames AND the built comparison result/banner.
  // (demo.clear alone only empties files, leaving the wipe video on screen → "Clear does nothing".)
  const clearDemo = () => {
    demo.clear();
    setDemoResult(null);
    setDemoBanner(null);
  };

  // grounded session Q&A → POST /session/{sid}/ask (sid via the same artifact-URL
  // trick refillKey uses); the pending turn renders as a typing indicator.
  const onAsk = async (q: string) => {
    const ref = result?.artifacts?.montage || result?.artifacts?.video;
    const sid = ref ? ref.split("/")[2] : null;
    if (!sid) return;
    const n = qaTurns.length;
    setQaTurns((prev) => [...prev, { q, answer: null }]);
    try {
      const r = await askQuestion(sid, q);
      setQaTurns((prev) =>
        prev.map((t, i) =>
          i === n ? { ...t, answer: r.answer, grounded: r.grounded } : t,
        ),
      );
    } catch {
      setQaTurns((prev) =>
        prev.map((t, i) =>
          i === n
            ? {
                ...t,
                answer:
                  "Couldn't reach the assistant — is the service running? Try again.",
                grounded: false,
              }
            : t,
        ),
      );
    }
  };

  const msgs = useMemo(
    () => deriveMessages({ upload, log, result, running, banner, qa: qaTurns }),
    [upload, log, result, running, banner, qaTurns],
  );
  const openBoard = (focus: number | null) => {
    setBoardFocus(focus);
    setView("board");
  };

  return (
    <div className="app">
      {view === "chat" ? (
        <div className="chat-page">
          <ChatHeader />
          {!upload && log.length === 0 && !result && (
            <ChatWelcome
              onImportFrames={importFrames}
              onImportVideo={importVideo}
            />
          )}
          <ChatView
            msgs={msgs}
            keyUrls={effKeyUrls}
            onOpenBoard={openBoard}
            onRefill={refillKey}
            onExport={downloadBundle}
          />
          <ChatComposer
            files={keys.files}
            fileUrls={keyUrls}
            onAdd={keys.add}
            onRemove={keys.remove}
            onClear={() => {
              clearAll();
              setVideoFile(null);
            }}
            mode={mode}
            onModeChange={changeMode}
            engines={engines}
            setEngines={setEngines}
            fps={fps}
            setFps={setFps}
            videoFile={videoFile}
            onVideo={setVideoFile}
            stride={stride}
            setStride={setStride}
            onRun={run}
            onRunVideo={runVideo}
            running={running}
            compact={running || log.length > 0}
            askEnabled={!!result?.artifacts}
            onAsk={onAsk}
            plantedCases={plantedCases}
            onRunPlanted={runPlanted}
          />
        </div>
      ) : (
        <>
          <div className="board-bar">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setView("chat")}
            >
              ← Back to chat
            </button>
          </div>
          <ReviewWorkbench
            log={log}
            result={result}
            running={running}
            keyUrls={effKeyUrls}
            verdicts={verdicts}
            onVerdict={setVerdict}
            onRefill={refillKey}
            fps={Number(fps) || 24}
            initialFocus={boardFocus}
            compareSlot={
              <Compare
                files={demo.files}
                onAdd={demo.add}
                onClear={clearDemo}
                onBuild={buildDemo}
                building={demoBuilding}
                banner={demoBanner}
                result={demoResult}
              />
            }
          />
        </>
      )}
      {banner && (
        <Toast key={banner} message={banner} onClose={() => setBanner(null)} />
      )}
    </div>
  );
}
