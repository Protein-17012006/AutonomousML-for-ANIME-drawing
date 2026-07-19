"use client";
// Co-pilot app shell — owns all session state and switches the chat ⇄ board surfaces.
// The presentational pieces were split out into ./components/* and the logic into ./lib/*
// (this file used to be a ~1360-line monolith holding all of them).
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { PairEvent, ResultEvent, DemoResult, InputMode } from "./types";
import { runSession, runDemo, runVideoSession, askQuestion } from "./api";
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
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import {
  AppSidebar,
  type SidebarAccount,
} from "@/components/common/AppSidebar";
import {
  authenticatedFetch,
  getCookieSession,
  logoutCookieSession,
} from "@/lib/authenticatedApi";
import {
  createMySession,
  getMySession,
  listMySessions,
  renameMySession,
  type PublishedSessionSummary,
} from "@/lib/sessionApi";

/* cadence value → human "shoot on Ns" label, shared by the upload bubble + the result sampling badge */
const CADENCE_LABEL: Record<string, string> = {
  "24": "on-1s",
  "12": "on-2s",
  "8": "on-3s",
};

function sidFromResult(r: ResultEvent | null) {
  const ref = r?.artifacts?.montage || r?.artifacts?.video;
  return ref?.startsWith("/session/") ? (ref.split("/")[2] ?? null) : null;
}

export default function App() {
  const router = useRouter();
  const keys = useFileSet();
  const demo = useFileSet();
  const [engines, setEngines] = useState("box");
  // cadence = shoot-on-Ns rate the artist drew at (24/12/8); smoothness = the in-between
  // multiplier applied on top (1=off, 2=standard, 4=extra — Phase 2 enables Extra).
  const [cadence, setCadence] = useState("12");
  const [smoothness, setSmoothness] = useState("2");

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

  // Auth
  const [account, setAccount] = useState<SidebarAccount | null>(null);
  const [liveSid, setLiveSid] = useState<string | null>(null);
  const [history, setHistory] = useState<PublishedSessionSummary[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectedPid, setSelectedPid] = useState<string | null>(null);
  const [activeDraftPid, setActiveDraftPid] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const page = await listMySessions();
      setHistory(page.items);
      setHistoryCursor(page.next_cursor);
      return page.items;
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "Could not load sessions.");
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    getCookieSession()
      .then((session) => {
        if (!active) return;
        setAccount({
          name: session.username || "Animator",
          email: session.username || undefined,
        });
        void loadHistory();
      })
      .catch((err) => {
        console.error("failed to load cookie session:", err);
        router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [loadHistory, router]);

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
    setLiveSid(null);
  };

  const selectHistorySession = async (session: PublishedSessionSummary) => {
    setSelectedPid(session.pid);
    if (session.status === "draft") {
      clearAll();
      setVideoFile(null);
      setActiveDraftPid(session.pid);
    } else {
      setActiveDraftPid(null);
    }
    try {
      const selected = await getMySession(session.pid);
      setHistory((items) => items.map((item) => item.pid === selected.pid ? selected : item));
      if (process.env.NODE_ENV === "development") {
        console.info("[selected-session-summary]", selected);
      }
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "Could not load session.");
    }
  };

  const createHistorySession = async (title: string) => {
    const created = await createMySession(title);
    setHistory((items) => [created, ...items.filter((item) => item.pid !== created.pid)]);
    setSelectedPid(created.pid);
    setActiveDraftPid(created.pid);
    clearAll();
    setVideoFile(null);
  };

  const renameHistorySession = async (pid: string, title: string) => {
    const renamed = await renameMySession(pid, title);
    setHistory((items) => items.map((item) => item.pid === pid ? renamed : item));
  };

  const loadMoreHistory = async () => {
    if (!historyCursor || historyLoadingMore) return;
    setHistoryLoadingMore(true);
    setHistoryError(null);
    try {
      const page = await listMySessions(20, historyCursor);
      setHistory((items) => [
        ...items,
        ...page.items.filter((next) => !items.some((item) => item.pid === next.pid)),
      ]);
      setHistoryCursor(page.next_cursor);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "Could not load more sessions.");
    } finally {
      setHistoryLoadingMore(false);
    }
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
    setLiveSid(null);
    setUpload({
      label: `${keys.files.length} keyframes · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"} · ${CADENCE_LABEL[cadence] ?? cadence} · ×${smoothness}`,
      thumbs: keyUrls.slice(0, 6),
    });
    setRunning(true);
    try {
      await runSession(keys.files, engines, cadence, smoothness, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => {
          setResult(r);
          setLiveSid(sidFromResult(r));
        },
        onError: (m) => setBanner(m),
      }, activeDraftPid);
      const refreshed = await loadHistory();
      if (activeDraftPid && refreshed.some((item) => item.pid === activeDraftPid && item.status === "complete")) {
        setActiveDraftPid(null);
      }
    } catch (err) {
      console.error("run session failed:", err);
      setBanner(
        "Couldn't reach the co-pilot — is the service running? Press Run to retry.",
      );
    } finally {
      setRunning(false);
    }
  };

  const runVideo = async () => {
    if (!videoFile) return;
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setLiveSid(null);
    setUpload({
      label: `${videoFile.name} · stride ${stride} · ${engines === "box" ? "Co-pilot (GPU)" : "Demo"}`,
      thumbs: [],
    });
    setRunning(true);
    try {
      await runVideoSession(videoFile, stride, cadence, smoothness, engines, {
        onPair: (p) => setLog((prev) => [...prev, p]),
        onResult: (r) => {
          setResult(r);
          setLiveSid(sidFromResult(r));
        },
        onError: (m) => setBanner(m),
      }, activeDraftPid);
      const refreshed = await loadHistory();
      if (activeDraftPid && refreshed.some((item) => item.pid === activeDraftPid && item.status === "complete")) {
        setActiveDraftPid(null);
      }
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
    if (!liveSid) return;
    const fd = new FormData();
    fd.append("index", String(index));
    fd.append("key", file);
    try {
      const resp = await authenticatedFetch(`/session/${liveSid}/key`, {
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
      setLiveSid(sidFromResult(d.result));
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
      // the full-cut Compare panel is a separate legacy demo (not wired to the chat composer's
      // cadence/smoothness controls) — kept at its historical default playback rate.
      setDemoResult(await runDemo(demo.files, engines, "24"));
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
    if (!liveSid) return;
    const n = qaTurns.length;
    setQaTurns((prev) => [...prev, { q, answer: null }]);
    try {
      const r = await askQuestion(liveSid, q);
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

  const handleSignOut = async () => {
    clearAll();
    await logoutCookieSession();
  };

  const msgs = useMemo(
    () => deriveMessages({ upload, log, result, running, banner, qa: qaTurns }),
    [upload, log, result, running, banner, qaTurns],
  );
  const openBoard = (focus: number | null) => {
    setBoardFocus(focus);
    setView("board");
  };
  // A session is "live" once anything has been staged/streamed. Drives the chat surface's
  // middle region: welcome (empty) XOR transcript (live) — exactly one flex-1 child so they
  // don't split the column and leave a gap above the docked composer.
  const hasSession = !!upload || log.length > 0 || !!result;

  return (
    <TooltipProvider>
      {/* App shell — left sidebar rail + the main content column (.app). */}
      <SidebarProvider className="copilot-shell">
        <AppSidebar
          account={account}
          onSignOut={handleSignOut}
          sessions={history}
          selectedPid={selectedPid}
          historyLoading={historyLoading}
          historyLoadingMore={historyLoadingMore}
          historyError={historyError}
          hasMoreSessions={Boolean(historyCursor)}
          onSelectSession={(session) => void selectHistorySession(session)}
          onCreateSession={createHistorySession}
          onRenameSession={renameHistorySession}
          onRetryHistory={() => void loadHistory()}
          onLoadMore={() => void loadMoreHistory()}
        />
        <div className="app">
          {view === "chat" ? (
            <div className="chat-page">
              <ChatHeader />
              {/* Middle region — welcome XOR transcript, never both (see hasSession). */}
              {hasSession ? (
                <ChatView
                  msgs={msgs}
                  keyUrls={effKeyUrls}
                  onOpenBoard={openBoard}
                  onRefill={refillKey}
                  onExport={downloadBundle}
                />
              ) : (
                <ChatWelcome
                  onImportFrames={importFrames}
                  onImportVideo={importVideo}
                />
              )}
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
                cadence={cadence}
                setCadence={setCadence}
                smoothness={smoothness}
                setSmoothness={setSmoothness}
                videoFile={videoFile}
                onVideo={setVideoFile}
                stride={stride}
                setStride={setStride}
                onRun={run}
                onRunVideo={runVideo}
                running={running}
                compact={running || log.length > 0}
                askEnabled={!!result?.artifacts && !!liveSid}
                onAsk={onAsk}
              />
            </div>
          ) : (
            <>
              <div className="board-bar">
                <Button
                  variant="outline"
                  type="button"
                  className="font-mono text-[12.5px] tracking-[0.02em]"
                  onClick={() => setView("chat")}
                >
                  ← Back to chat
                </Button>
              </div>
              <ReviewWorkbench
                log={log}
                result={result}
                running={running}
                keyUrls={effKeyUrls}
                verdicts={verdicts}
                onVerdict={setVerdict}
                onRefill={refillKey}
                fps={
                  result?.sampling?.output_fps ||
                  Number(cadence) * Number(smoothness) ||
                  24
                }
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
            <Toast
              key={banner}
              message={banner}
              onClose={() => setBanner(null)}
            />
          )}
        </div>
      </SidebarProvider>
    </TooltipProvider>
  );
}
