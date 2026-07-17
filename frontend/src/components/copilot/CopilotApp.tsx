"use client";
// Co-pilot app shell — owns all session state and switches the chat ⇄ board surfaces.
// The presentational pieces were split out into ./components/* and the logic into ./lib/*
// (this file used to be a ~1360-line monolith holding all of them).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchUserAttributes, getCurrentUser, signOut } from "aws-amplify/auth";
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
import {
  AppSidebar,
  type SidebarAccount,
} from "@/components/common/AppSidebar";
import { authHeaders, getIdentityId } from "@/lib/amplify";
import {
  createConversation,
  getConversationState,
  listConversations,
  makeConversationMeta,
  newConversationId,
  persistSessionImages,
  putConversationState,
  updateConversationMeta,
} from "@/lib/chatStore";
import type {
  ConversationMeta,
  ConversationState,
  SessionKind,
} from "@/models/conversation";

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
  const [identityId, setIdentityId] = useState<string | null>(null);
  const [account, setAccount] = useState<SidebarAccount | null>(null);
  const [cid, setCid] = useState<string | null>(null);
  const [liveSid, setLiveSid] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [saving, setSaving] = useState(false);
  const lastSavedRef = useRef<string | null>(null);
  const lightSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshConversations = useCallback(
    async (id = identityId) => {
      if (!id) return;
      setConversations(await listConversations(id));
    },
    [identityId],
  );

  useEffect(() => {
    let active = true;
    Promise.all([getCurrentUser(), getIdentityId(), fetchUserAttributes()])
      .then(([user, id, attrs]) => {
        if (!active) return;
        setIdentityId(id);
        setAccount({
          name: attrs.name || attrs.email || user.username,
          email: attrs.email,
        });
        return listConversations(id);
      })
      .then((items) => {
        if (active && items) setConversations(items);
      })
      .catch((err) => {
        console.error("failed to load Cognito user:", err);
        router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [router]);

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
    setCid(null);
    setLiveSid(null);
    lastSavedRef.current = null;
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
    setCid(null);
    setLiveSid(null);
    lastSavedRef.current = null;
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
      });
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
    setCid(null);
    setLiveSid(null);
    lastSavedRef.current = null;
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
    if (!liveSid) return;
    const fd = new FormData();
    fd.append("index", String(index));
    fd.append("key", file);
    try {
      const resp = await fetch(`/session/${liveSid}/key`, {
        method: "POST",
        headers: await authHeaders(),
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

  const currentState = useCallback(
    (): ConversationState => ({
      schemaVersion: 1,
      upload,
      log,
      result,
      qaTurns,
      verdicts,
    }),
    [upload, log, result, qaTurns, verdicts],
  );

  useEffect(() => {
    if (!identityId || !result || running) return;
    const marker = result.artifacts?.montage || result.artifacts?.video;
    if (!marker || lastSavedRef.current === marker) return;

    let cancelled = false;
    async function saveCompletedRun() {
      if (!identityId || !result || !upload) return;
      setSaving(true);
      try {
        const nextCid = cid ?? newConversationId();
        const persisted = await persistSessionImages({
          cid: nextCid,
          identityId,
          state: currentState(),
          keyFiles: keys.files,
          videoFile,
        });
        if (cancelled) return;
        const kind: SessionKind = videoFile ? "video" : "png";
        const meta = makeConversationMeta({
          identityId,
          cid: nextCid,
          title: upload.label,
          kind,
          engines,
          fps: Number(cadence) || 12,
          stride: Number(stride) || 2,
          sid: liveSid,
          uploadLabel: upload.label,
          thumb: persisted.result?.artifacts?.montage ?? null,
        });
        if (cid) {
          await updateConversationMeta(identityId, nextCid, {
            title: meta.title,
            kind: meta.kind,
            engines: meta.engines,
            fps: meta.fps,
            stride: meta.stride,
            sid: meta.sid,
            uploadLabel: meta.uploadLabel,
            thumb: meta.thumb,
            updatedAt: meta.updatedAt,
            schemaVersion: meta.schemaVersion,
          });
        } else {
          await createConversation(meta);
        }
        if (cancelled) return;
        setCid(nextCid);
        lastSavedRef.current = marker ?? null;
        await refreshConversations(identityId);
      } catch (err) {
        console.error("save conversation failed:", err);
        if (!cancelled)
          setBanner("Session finished, but saving history failed.");
      } finally {
        if (!cancelled) setSaving(false);
      }
    }

    void saveCompletedRun();
    return () => {
      cancelled = true;
    };
  }, [
    cadence,
    cid,
    currentState,
    engines,
    identityId,
    keys.files,
    liveSid,
    refreshConversations,
    result,
    running,
    stride,
    upload,
    videoFile,
  ]);

  useEffect(() => {
    if (!identityId || !cid || !result) return;
    if (lightSaveTimer.current) clearTimeout(lightSaveTimer.current);
    lightSaveTimer.current = setTimeout(() => {
      setSaving(true);
      putConversationState(identityId, cid, currentState())
        .then(() =>
          updateConversationMeta(identityId, cid, {
            updatedAt: Date.now(),
          }),
        )
        .then(() => refreshConversations(identityId))
        .catch((err) => {
          console.error("light save failed:", err);
        })
        .finally(() => setSaving(false));
    }, 800);
    return () => {
      if (lightSaveTimer.current) clearTimeout(lightSaveTimer.current);
    };
  }, [
    cid,
    currentState,
    identityId,
    qaTurns,
    refreshConversations,
    result,
    verdicts,
  ]);

  const openConversation = async (conversation: ConversationMeta) => {
    if (!identityId) return;
    setSaving(true);
    try {
      const state = await getConversationState(identityId, conversation.cid);
      keys.clear();
      setVideoFile(null);
      setUpload(state.upload);
      setLog(state.log);
      setResult(state.result);
      setQaTurns(state.qaTurns);
      setVerdicts(state.verdicts);
      setCid(conversation.cid);
      setLiveSid(null);
      lastSavedRef.current =
        state.result?.artifacts?.montage || `restore:${conversation.cid}`;
      setView("chat");
      setBanner(null);
    } catch (err) {
      console.error("open conversation failed:", err);
      setBanner("Couldn't open that saved chat.");
    } finally {
      setSaving(false);
    }
  };

  const startNewChat = () => {
    clearAll();
    setVideoFile(null);
  };

  const handleSignOut = async () => {
    await signOut();
    setConversations([]);
    router.replace("/login");
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
          conversations={conversations}
          activeCid={cid}
          saving={saving}
          account={account}
          onSelect={openConversation}
          onNewChat={startNewChat}
          onSignOut={handleSignOut}
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
