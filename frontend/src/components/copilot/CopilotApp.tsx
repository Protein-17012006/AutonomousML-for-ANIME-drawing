"use client";
// Co-pilot app shell — owns all session state and switches the chat ⇄ board surfaces.
// The presentational pieces were split out into ./components/* and the logic into ./lib/*
// (this file used to be a ~1360-line monolith holding all of them).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { PairEvent, ResultEvent, InputMode } from "./types";
import {
  runSession,
  runVideoSession,
  askAgent,
  askQuestion,
  rerunSession,
  rememberMemory,
  submitReplacementKeys,
  submitVerdicts,
  submitRepair,
  runOrchestration,
  type AgentAction,
  type TranscriptEntry,
} from "./api";
import {
  type ChatMsg,
  deriveMessages,
  type QaTurn,
  type UserTurn,
} from "./lib/chatModel";
import { useFileSet } from "./lib/useFileSet";
import { downloadBundle } from "./lib/exportSession";
import { ChatHeader } from "./components/chat/ChatHeader";
import { ChatView } from "./components/chat/ChatView";
import { ChatComposer } from "./components/chat/ChatComposer";
import { ChatWelcome } from "./components/chat/ChatWelcome";
import { ReviewWorkbench } from "./components/review/ReviewWorkbench";
import { ActiveWorkspaceDialog } from "./components/common/ActiveWorkspaceDialog";
import { Toast } from "./components/review/Toast";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { LoaderCircle } from "lucide-react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  AppSidebar,
  type SidebarAccount,
} from "./components/common/AppSidebar";
import {
  authenticatedFetch,
  getCookieSession,
  logoutCookieSession,
} from "@/lib/authenticatedApi";
import {
  createMySession,
  deleteMySession,
  getMySession,
  getMySessionWorkspace,
  listMySessions,
  renameMySession,
  resumeMySession,
  type PublishedSessionSummary,
} from "@/lib/sessionApi";
import { discardActiveWorkspace, getActiveWorkspace, retryActiveWorkspacePublish, subscribeActiveWorkspace, type ActiveWorkspace } from "@/lib/activeWorkspace";
import { clearCache, deleteActiveWorkspaceDatabase, loadCache, purgeForeignCaches, saveAssets, saveState, type CachedState } from "@/lib/activeWorkspaceCache";

function sidFromResult(r: ResultEvent | null) {
  // The server sends the id outright. Slicing an artifact URL is the fallback for
  // sessions stored before that field existed: a republished session serves them
  // under "/sessions/{pid}/artifacts/...", which this slice cannot read, and the
  // grounded Q&A box then goes dead with no visible cause.
  if (r?.sid != null) return String(r.sid);
  const ref = r?.artifacts?.montage || r?.artifacts?.video;
  return ref?.startsWith("/session/") ? (ref.split("/")[2] ?? null) : null;
}

type PendingRun =
  | { kind: "frames"; files: File[] }
  | { kind: "video"; file: File };

function insertReplacementKeys(
  current: File[],
  submitted: Record<number, { file: File; url: string }>,
): File[] {
  // The backend receives original gap indices and inserts in descending order,
  // so each index remains anchored to the pre-refill timeline. Mirror that
  // order here to keep every review pair aligned with its two key frames.
  const expanded = [...current];
  for (const index of Object.keys(submitted).map(Number).sort((a, b) => b - a)) {
    expanded.splice(index + 1, 0, submitted[index].file);
  }
  return expanded;
}

export default function App() {
  const router = useRouter();
  // `keys` are media belonging to the displayed session. The
  // composer gets its own staging buffer, so editing a prospective new run can
  // never erase a selected completed session.
  const keys = useFileSet();
  const stagedKeys = useFileSet();
  const engines = "box";
  const [interpolator, setInterpolator] = useState("rife");
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
  const [stagedRefills, setStagedRefills] = useState<Record<number, { file: File; url: string }>>({});
  const stagedRefillsRef = useRef<Record<number, { file: File; url: string }>>({});
  const [reviewSubmit, setReviewSubmit] = useState<{ kind: "verdicts" | "keys" | "repair"; phase: string; error?: string } | null>(null);
  const setVerdict = (idx: number, v: "accept" | "reject") => {
    // Staged only. The artist's keep/redraw IS the per-show calibration signal
    // the QA thresholds are refit against, but it reaches the feedback store
    // through "Submit verdicts" → POST /session/{sid}/feedback/batch, after the
    // durable review revision is published. Firing per toggle (which is what
    // this did on its own branch) posted to /session/{sid}/feedback — a route
    // that no longer exists — and would have filed a calibration record for a
    // choice the artist can still undo before submitting.
    setVerdicts((prev) => {
      const n = { ...prev };
      if (n[idx] === v)
        delete n[idx]; // toggle off
      else n[idx] = v;
      return n;
    });
  };

  const discardStagedRefills = useCallback(() => {
    for (const item of Object.values(stagedRefillsRef.current)) URL.revokeObjectURL(item.url);
    stagedRefillsRef.current = {};
    setStagedRefills({});
  }, []);

  useEffect(() => () => {
    for (const item of Object.values(stagedRefillsRef.current)) URL.revokeObjectURL(item.url);
  }, []);

  const [stagedVideoFile, setStagedVideoFile] = useState<File | null>(null);
  const [stride, setStride] = useState("2");
  // Composer input mode, lifted here (was in ChatComposer) so BOTH the dropzone and the
  // ChatWelcome quick-import buttons share one source of truth.
  const [stagedMode, setStagedMode] = useState<InputMode>("frames");
  const [sessionMode, setSessionMode] = useState<InputMode>("frames");


  // chat-first surface state (vault 'Chat-First Copilot Surface')
  const [view, setView] = useState<"chat" | "board">("chat");
  // Opening the board is a navigation as far as the artist is concerned, but it
  // changed no URL — so Back left the app entirely and the remount lost the
  // conversation. Push one history entry when the board opens and treat Back as
  // "return to the chat", so nothing unmounts.
  useEffect(() => {
    const onPop = () => setView("chat");
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    if (view !== "board") return;
    const current = window.history.state as Record<string, unknown> | null;
    if (current?.copilotView === "board") return;   // already pushed
    // Spread the router's own state: replacing it wholesale would strip what
    // Next.js keeps there and break client-side navigation.
    window.history.pushState({ ...(current ?? {}), copilotView: "board" }, "");
  }, [view]);
  const [boardFocus, setBoardFocus] = useState<number | null>(null);
  // The pair whose burnt-in QA mark the agent was asked to show. The nonce makes
  // a second request for the SAME pair a distinct event, so asking again after
  // the artist toggled the mark off turns it back on.
  const [boardMark, setBoardMark] = useState<{ index: number; nonce: number } | null>(null);
  const [upload, setUpload] = useState<UserTurn | null>(null);
  const [qaTurns, setQaTurns] = useState<QaTurn[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  // Opt-in. The planner has never been user-facing, and deciding what to do with
  // an artist's cut is a bigger promise than answering their question — so it is
  // a choice they make per message, not a default applied to all of them.
  const [planMode, setPlanMode] = useState(false);

  // Auth
  const [account, setAccount] = useState<SidebarAccount | null>(null);
  const [ownerSub, setOwnerSub] = useState<string | null>(null);
  const [liveSid, setLiveSid] = useState<string | null>(null);
  const [durablePid, setDurablePid] = useState<string | null>(null);
  // Why a reopened session stayed read-only. Null means it did not — either it
  // resumed, or nothing has been reopened.
  const [resumeRefusal, setResumeRefusal] = useState<string | null>(null);
  const [history, setHistory] = useState<PublishedSessionSummary[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectedPid, setSelectedPid] = useState<string | null>(null);
  const [activeDraftPid, setActiveDraftPid] = useState<string | null>(null);
  const [recoverableWorkspace, setRecoverableWorkspace] = useState<ActiveWorkspace | null>(null);
  const [activeWorkspace, setActiveWorkspace] = useState<ActiveWorkspace | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [preflightWorkspace, setPreflightWorkspace] = useState<ActiveWorkspace | null>(null);
  const [pendingRun, setPendingRun] = useState<PendingRun | null>(null);
  const cacheWritesEnabled = useRef(false);
  const activeStreamStop = useRef<(() => void) | null>(null);
  // The session hydration currently in flight. Resume is an await inside that
  // hydration, so a second click during it must not let the first one install a
  // live id belonging to the cut the artist just navigated away from.
  const hydratingPid = useRef<string | null>(null);
  const activeStreamSequence = useRef(0);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const page = await listMySessions();
      setHistory(page.items);
      setHistoryCursor(page.next_cursor);
      return page.items;
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Could not load sessions.",
      );
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const hydratePublishedSession = useCallback(async (
    pid: string,
    { retainLiveSession = false }: { retainLiveSession?: boolean } = {},
  ) => {
    const [selected, workspace] = await Promise.all([
      getMySession(pid),
      getMySessionWorkspace(pid),
    ]);
    setHistory((items) => {
      const existing = items.findIndex((item) => item.pid === selected.pid);
      if (existing < 0) return [selected, ...items];
      return items.map((item) => (item.pid === selected.pid ? selected : item));
    });

    if (!retainLiveSession) {
      setSelectedPid(selected.pid);
      setActiveDraftPid(null);
      keys.clear();
      // A completed session owns only the media displayed in `keys`/its durable
      // result. Do not carry a previous run's prospective composer files into
      // this read-only view: `useFileSet.add` deliberately de-duplicates a
      // reselected File, which otherwise makes a new upload look ignored until
      // the artist presses Clear.
      stagedKeys.clear();
      setStagedVideoFile(null);
      setStagedMode(workspace.upload.mode);
    }
    setSessionMode(workspace.upload.mode);
    setUpload({
      media: workspace.upload.mode === "video" ? "video" : "keyframes",
      count: workspace.upload.filenames.length,
    });
    setLog(workspace.pairs);
    setResult(workspace.result);
    // A snapshot's own SID is dead: it names a runtime session in a process that
    // has since restarted or evicted it. Clear it, then ask the service to build
    // a NEW one from this snapshot — that is what makes the reopened workbench
    // editable instead of a read-only record of a session the artist can no
    // longer touch.
    if (!retainLiveSession) {
      setLiveSid(null);
      setResumeRefusal(null);
      hydratingPid.current = selected.pid;
    }
    setDurablePid(selected.pid);
    setQaTurns(workspace.qa.map((turn) => ({
      q: turn.question,
      answer: turn.answer,
      grounded: turn.grounded,
    })));
    setVerdicts({});
    setRunning(false);
    setView("chat");

    if (retainLiveSession || selected.status !== "complete") return;
    try {
      const resumed = await resumeMySession(selected.pid);
      if (hydratingPid.current !== selected.pid) return;
      setLiveSid(resumed.sid);
      setResumeRefusal(resumed.reason);
    } catch {
      if (hydratingPid.current !== selected.pid) return;
      setResumeRefusal("This session could not be reopened for editing just now.");
    }
  }, [keys, stagedKeys]);

  const finishRecoveredPublication = useCallback(async (pid: string) => {
    // Stop accepting cache writes before awaiting durable reads. The publish
    // receipt is authoritative even if a subsequent history read fails.
    activeStreamStop.current?.();
    activeStreamStop.current = null;
    setActiveWorkspace(null);
    setRecoverableWorkspace(null);
    if (ownerSub) await clearCache(ownerSub);
    await loadHistory();
    await hydratePublishedSession(pid);
  }, [hydratePublishedSession, loadHistory, ownerSub]);

  const startActiveWorkspaceStream = useCallback((workspace: ActiveWorkspace, after: number) => {
    activeStreamStop.current?.();
    activeStreamSequence.current = after;
    activeStreamStop.current = subscribeActiveWorkspace(workspace.workspace_id, after, {
      onEvent: (event) => {
        activeStreamSequence.current = event.sequence;
        setActiveWorkspace((current) => ({
          ...(current?.workspace_id === workspace.workspace_id ? current : workspace),
          event_sequence: event.sequence,
          ...(event.name === "publish" && event.data.published !== true ? { state: "publish_pending" } : {}),
        }));
        if (event.name === "pair") {
          const pair = event.data as unknown as PairEvent;
          if (typeof pair.index === "number" && typeof pair.action === "string") {
            setLog((previous) => previous.some((item) => item.index === pair.index)
              ? previous.map((item) => item.index === pair.index ? pair : item)
              : [...previous, pair]);
            setRunning(true);
          }
        } else if (event.name === "result") {
          const next = event.data as unknown as ResultEvent;
          if (typeof next.n_autopass === "number") {
            setResult(next);
            setLiveSid(sidFromResult(next));
          }
        } else if (event.name === "error") {
          setRunning(false);
          setBanner(typeof event.data.message === "string" ? event.data.message : "The recovered workspace stopped unexpectedly.");
        } else if (event.name === "publish") {
          setRunning(false);
          if (event.data.published === true) {
            const pid = typeof event.data.pid === "string" ? event.data.pid : null;
            if (!pid) {
              setRecoveryError("The session was published but no history ID was returned.");
              return;
            }
            void finishRecoveredPublication(pid).catch((error) => {
              setRecoveryError(error instanceof Error ? error.message : "Could not load the published session.");
            });
          } else {
            const pendingWorkspace: ActiveWorkspace = {
              ...workspace,
              state: "publish_pending",
              event_sequence: event.sequence,
            };
            setActiveWorkspace(pendingWorkspace);
            setRecoverableWorkspace(pendingWorkspace);
            setRecoveryError(typeof event.data.error === "string" ? event.data.error : "The session is ready, but publishing needs a retry.");
          }
        }
      },
      onConnectionError: () => {
        // The subscription reconnects from its persisted sequence automatically.
      },
    });
  }, [finishRecoveredPublication]);

  useEffect(() => () => activeStreamStop.current?.(), []);
  // Account Setup
  useEffect(() => {
    let active = true;
    getCookieSession()
      .then(async (session) => {
        // Finish shared-browser cleanup before this account can write another
        // cache entry. A failed cleanup leaves caching disabled for safety.
        let cacheReady = true;
        try {
          await purgeForeignCaches(session.user_sub);
        } catch (error) {
          cacheReady = false;
          console.warn("could not purge another account's workspace cache", error);
        }
        if (!active) return;
        cacheWritesEnabled.current = cacheReady;
        setAccount({
          name: session.name,
          username: session.username,
        });
        setOwnerSub(session.user_sub);
        void loadHistory();
        void getActiveWorkspace().then(async (workspace) => {
          if (workspace?.published_pid) {
            // A receipt proves that this draft is already durable. It is not a
            // user-selected history session, so do not change sidebar selection
            // or hydrate it into the current view on page entry.
            await clearCache(session.user_sub);
            return;
          }
          setRecoverableWorkspace(workspace);
        }).catch((error: unknown) =>
          setRecoveryError(error instanceof Error ? error.message : "Could not inspect the active workspace."),
        );
      })
      .catch((err) => {
        cacheWritesEnabled.current = false;
        console.error("failed to load cookie session:", err);
        router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [loadHistory, router]);

  const keyUrls = useMemo(
    () => keys.files.map((f) => URL.createObjectURL(f)),
    [keys.files],
  );
  useEffect(
    () => () => keyUrls.forEach((u) => URL.revokeObjectURL(u)),
    [keyUrls],
  );

  const stagedKeyUrls = useMemo(
    () => stagedKeys.files.map((f) => URL.createObjectURL(f)),
    [stagedKeys.files],
  );
  useEffect(
    () => () => stagedKeyUrls.forEach((u) => URL.revokeObjectURL(u)),
    [stagedKeyUrls],
  );

  const effKeyUrls = useMemo(() => {
    const sk = result?.key_urls;
    const serverUrls = sk
      ? Array.from({ length: Object.keys(sk).length }, (_, i) => sk[String(i)] ?? "")
      : [];
    // Video sessions and durable reloads have server-owned key pixels. After
    // a refill revision, prefer that complete map if the browser has fewer
    // local files than the expanded timeline.
    return serverUrls.length > keyUrls.length ? serverUrls : keyUrls;
  }, [keyUrls, result]);

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
    setDurablePid(null);
    setResumeRefusal(null);
  };

  const restoreActiveInputs = async (workspace: ActiveWorkspace) => {
    const inputs = workspace.assets.filter((asset) => asset.kind === "input-key" || asset.kind === "input-video");
    const fetchInput = async (name: string) => {
      const url = workspace.artifact_urls[name];
      if (!url) throw new Error("The active workspace is missing a protected input URL.");
      const response = await authenticatedFetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`Could not restore an uploaded asset (${response.status}).`);
      return response.blob();
    };
    const video = inputs.find((asset) => asset.kind === "input-video");
    if (video) {
      const blob = await fetchInput(video.name);
      keys.clear();
      const restoredVideo = new File([blob], workspace.snapshot.upload?.filenames?.[0] ?? "video.mp4", { type: blob.type || "video/mp4" });
      stagedKeys.clear();
      setStagedVideoFile(restoredVideo);
      setStagedMode("video");
      setSessionMode("video");
      return { keys: [], video: restoredVideo };
    }
    const frames = inputs.filter((asset) => asset.kind === "input-key").sort((a, b) => a.name.localeCompare(b.name));
    const files = await Promise.all(frames.map(async (asset, index) => {
      const blob = await fetchInput(asset.name);
      return new File([blob], workspace.snapshot.upload?.filenames?.[index] ?? asset.name, { type: blob.type || "image/png" });
    }));
    keys.replace(files);
    stagedKeys.replace(files);
    setStagedVideoFile(null);
    setStagedMode("frames");
    setSessionMode("frames");
    return { keys: files, video: null };
  };

  useEffect(() => {
    if (!cacheWritesEnabled.current || !ownerSub || (!activeWorkspace && !recoverableWorkspace) || activeWorkspace?.state === "published" || recoverableWorkspace?.state === "published" || (!running && !upload && log.length === 0 && !result)) return;
    const state: Omit<CachedState, "expiresAt"> = {
      revision: activeWorkspace?.revision ?? recoverableWorkspace?.revision ?? null,
      workspaceId: activeWorkspace?.workspace_id ?? recoverableWorkspace?.workspace_id ?? null,
      eventSequence: activeWorkspace?.event_sequence ?? activeStreamSequence.current,
      mode: sessionMode,
      upload,
      log,
      result,
      verdicts,
      activeDraftPid,
      qaTurns,
    };
    void saveState(ownerSub, state).catch((error) =>
      console.warn("could not cache active workspace state", error),
    );
  }, [activeDraftPid, activeWorkspace, log, ownerSub, qaTurns, recoverableWorkspace, result, running, sessionMode, upload, verdicts]);

  const selectHistorySession = async (session: PublishedSessionSummary) => {
    setSelectedPid(session.pid);
    if (session.status === "draft") {
      clearAll();
      setActiveDraftPid(session.pid);
    } else {
      setActiveDraftPid(null);
    }
    try {
      if (session.status === "complete") {
        await hydratePublishedSession(session.pid);
        return;
      }
      const selected = await getMySession(session.pid);
      setHistory((items) => items.map((item) => (item.pid === selected.pid ? selected : item)));
      // This API type contains only the safe sidebar summary contract; log it
      // after a successful selection in every build so production support can
      // confirm the owner-scoped record returned by FastAPI.
      console.info("[selected-session-summary]", selected);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Could not load session.",
      );
    }
  };

  const createHistorySession = async (title: string) => {
    const created = await createMySession(title);
    setHistory((items) => [
      created,
      ...items.filter((item) => item.pid !== created.pid),
    ]);
    setSelectedPid(created.pid);
    setActiveDraftPid(created.pid);
    clearAll();
  };

  const renameHistorySession = async (pid: string, title: string) => {
    const renamed = await renameMySession(pid, title);
    setHistory((items) =>
      items.map((item) => (item.pid === pid ? renamed : item)),
    );
  };

  const loadMoreHistory = async () => {
    if (!historyCursor || historyLoadingMore) return;
    setHistoryLoadingMore(true);
    setHistoryError(null);
    try {
      const page = await listMySessions(20, historyCursor);
      setHistory((items) => [
        ...items,
        ...page.items.filter(
          (next) => !items.some((item) => item.pid === next.pid),
        ),
      ]);
      setHistoryCursor(page.next_cursor);
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Could not load more sessions.",
      );
    } finally {
      setHistoryLoadingMore(false);
    }
  };

  const clearComposerInputs = () => {
    stagedKeys.clear();
    setStagedVideoFile(null);
  };

  const changeMode = (next: InputMode) => {
    if (next === stagedMode) return;
    if (next === "video")
      stagedKeys.clear(); // leaving frames → drop staged keys
    else setStagedVideoFile(null); // leaving video → drop staged clip
    setStagedMode(next);
  };

  const importFrames = (picked: File[]) => {
    if (!picked.length) return;
    changeMode("frames");
    stagedKeys.add(picked);
  };

  const deleteHistorySession = async (pid: string) => {
    await deleteMySession(pid);
    const deletedDisplayedSession = selectedPid === pid || durablePid === pid;
    setHistory((items) => items.filter((item) => item.pid !== pid));
    if (deletedDisplayedSession) {
      setSelectedPid(null);
      setActiveDraftPid(null);
      clearAll();
    }
    await loadHistory();
  };

  const importVideo = (file: File) => {
    changeMode("video");
    setStagedVideoFile(file);
  };

  const removeComposerFrame = (file: File) => {
    stagedKeys.remove(file);
  };

  const setComposerVideo = (file: File | null) => {
    if (file) {
      importVideo(file);
      return;
    }
    setStagedVideoFile(null);
  };

  const beginFrameRun = async (files: File[]) => {
    if (!activeDraftPid) setSelectedPid(null);
    clearAll();
    keys.replace(files);
    setSessionMode("frames");
    setBanner(null);
    setUpload({
      media: "keyframes",
      count: files.length,
    });
    setRunning(true);
    let discoveredWorkspace = false;
    const discoverWorkspace = () => {
      if (discoveredWorkspace) return;
      discoveredWorkspace = true;
      void getActiveWorkspace().then((workspace) => {
        if (!workspace) return;
        activeStreamSequence.current = workspace.event_sequence;
        setActiveWorkspace(workspace);
        if (cacheWritesEnabled.current && ownerSub) void saveAssets(ownerSub, files, null, workspace.workspace_id);
      }).catch(() => undefined);
    };
    try {
      if (cacheWritesEnabled.current && ownerSub) await saveAssets(ownerSub, files, null);
      await runSession(
        files,
        engines,
        interpolator,
        cadence,
        smoothness,
        {
          onPair: (p) => {
            setLog((prev) => [...prev, p]);
            discoverWorkspace();
          },
          onResult: (r) => {
            setResult(r);
            setLiveSid(sidFromResult(r));
          },
          onPublish: (published) => {
            if (published.published && published.pid) {
              setDurablePid(published.pid);
              void loadHistory();
              if (ownerSub) void clearCache(ownerSub);
              setActiveWorkspace(null);
              return;
            }
            setRecoveryError(
              published.error ?? "The session is ready, but publishing needs a retry.",
            );
            void getActiveWorkspace()
              .then((workspace) => {
                if (workspace) setRecoverableWorkspace(workspace);
              })
              .catch(() => undefined);
          },
          onError: (m) => setBanner(m),
        },
        activeDraftPid,
      );
      const refreshed = await loadHistory();
      if (
        activeDraftPid &&
        refreshed.some(
          (item) => item.pid === activeDraftPid && item.status === "complete",
        )
      ) {
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

  const beginVideoRun = async (file: File) => {
    if (!activeDraftPid) setSelectedPid(null);
    clearAll();
    setSessionMode("video");
    setBanner(null);
    setUpload({
      media: "video",
      count: 1,
    });
    setRunning(true);
    let discoveredWorkspace = false;
    const discoverWorkspace = () => {
      if (discoveredWorkspace) return;
      discoveredWorkspace = true;
      void getActiveWorkspace().then((workspace) => {
        if (!workspace) return;
        activeStreamSequence.current = workspace.event_sequence;
        setActiveWorkspace(workspace);
        if (cacheWritesEnabled.current && ownerSub) void saveAssets(ownerSub, [], file, workspace.workspace_id);
      }).catch(() => undefined);
    };
    try {
      if (cacheWritesEnabled.current && ownerSub) await saveAssets(ownerSub, [], file);
      await runVideoSession(
        file,
        stride,
        cadence,
        smoothness,
        engines,
        interpolator,
        {
          onPair: (p) => {
            setLog((prev) => [...prev, p]);
            discoverWorkspace();
          },
          onResult: (r) => {
            setResult(r);
            setLiveSid(sidFromResult(r));
          },
          onPublish: (published) => {
            if (published.published && published.pid) {
              setDurablePid(published.pid);
              void loadHistory();
              if (ownerSub) void clearCache(ownerSub);
              setActiveWorkspace(null);
              return;
            }
            setRecoveryError(
              published.error ?? "The session is ready, but publishing needs a retry.",
            );
            void getActiveWorkspace()
              .then((workspace) => {
                if (workspace) setRecoverableWorkspace(workspace);
              })
              .catch(() => undefined);
          },
          onError: (m) => setBanner(m),
        },
        activeDraftPid,
      );
      const refreshed = await loadHistory();
      if (
        activeDraftPid &&
        refreshed.some(
          (item) => item.pid === activeDraftPid && item.status === "complete",
        )
      ) {
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

  const beginPendingRun = async (next: PendingRun) => {
    if (next.kind === "frames") await beginFrameRun(next.files);
    else await beginVideoRun(next.file);
  };

  const requestRun = async (next: PendingRun) => {
    setBanner(null);
    setRecoveryError(null);
    try {
      const workspace = await getActiveWorkspace();
      if (workspace && !workspace.published_pid && workspace.state !== "published") {
        setPendingRun(next);
        setPreflightWorkspace(workspace);
        return;
      }
      if (workspace?.published_pid && ownerSub) await clearCache(ownerSub);
      await beginPendingRun(next);
    } catch (error) {
      setBanner(error instanceof Error
        ? `Could not check for an active workspace: ${error.message}`
        : "Could not check for an active workspace. Try again before starting a new run.");
    }
  };

  const run = () => {
    if (stagedKeys.files.length < 2) return;
    void requestRun({ kind: "frames", files: stagedKeys.files });
  };

  const runVideo = () => {
    if (!stagedVideoFile) return;
    void requestRun({ kind: "video", file: stagedVideoFile });
  };

  const refillKey = (index: number, file: File) => {
    if (!liveSid) return;
    const previous = stagedRefillsRef.current[index];
    if (previous) URL.revokeObjectURL(previous.url);
    const next = { file, url: URL.createObjectURL(file) };
    stagedRefillsRef.current = { ...stagedRefillsRef.current, [index]: next };
    setStagedRefills(stagedRefillsRef.current);
    /* Legacy per-key network mutation intentionally retired.
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
    */
  };

  const submitReviewVerdicts = () => {
    if (!liveSid || !durablePid || Object.keys(verdicts).length === 0) return;
    setReviewSubmit({ kind: "verdicts", phase: "Finalizing artist decisions" });
    void submitVerdicts(liveSid, verdicts, {
      onPair: () => undefined,
      // Keep the modal blocking until the durable snapshot has been fetched
      // and applied; the review SSE result only confirms the server commit.
      onResult: () => finalizeDurableReview(),
      onProgress: (phase) => setReviewSubmit({ kind: "verdicts", phase }),
      onError: (error) => setReviewSubmit({ kind: "verdicts", phase: "Could not submit", error }),
    });
  };

  const submitPairRepair = (pairIndex: number, maskPng: string) => {
    if (!liveSid || !durablePid) return;
    setReviewSubmit({ kind: "repair", phase: "Sending the painted region" });
    // frame 1 is the pair's generated middle -- the frame the workbench shows
    // and the only one the canvas can paint. Positions are pair-local.
    void submitRepair(liveSid, pairIndex, [{ frame: 1, png: maskPng }], {
      onPair: () => undefined,
      onResult: () => finalizeDurableReview(),
      onProgress: (phase) => setReviewSubmit({ kind: "repair", phase }),
      onError: (error) => setReviewSubmit({ kind: "repair", phase: "Could not repair", error }),
    });
  };

  const submitReviewKeys = () => {
    if (!liveSid || !durablePid) return;
    const needs = log.filter((pair) => pair.action === "needs_key");
    if (needs.length === 0 || needs.some((pair) => !stagedRefills[pair.index])) return;
    const submitted = stagedRefills;
    setReviewSubmit({ kind: "keys", phase: "Preparing replacement keys" });
    void submitReplacementKeys(liveSid, Object.fromEntries(Object.entries(submitted).map(([index, item]) => [Number(index), item.file])), {
      onPair: () => undefined,
      onResult: () => finalizeDurableReview(submitted),
      onProgress: (phase) => setReviewSubmit({ kind: "keys", phase }),
      onError: (error) => setReviewSubmit({ kind: "keys", phase: "Could not submit", error }),
    });
  };

  const finalizeDurableReview = async (submitted?: Record<number, { file: File; url: string }>) => {
    try {
      if (submitted) {
        keys.replace(insertReplacementKeys(keys.files, submitted));
        discardStagedRefills();
      }
      setVerdicts({});
      await loadHistory();
      if (durablePid) {
        await hydratePublishedSession(durablePid, { retainLiveSession: true });
      }
      setReviewSubmit(null);
    } catch (error) {
      setReviewSubmit({ kind: submitted ? "keys" : "verdicts", phase: "Saved, but could not reload", error: error instanceof Error ? error.message : "Reload the session from history." });
    }
  };

  // The chat used to call /ask, which answers and nothing more. It now calls the
  // agent, which answers AND may propose one tool. Nothing it proposes runs
  // here: acceptAction below is the only path, and the server refuses anything
  // confirm-gated that arrives without one.
  const onAsk = async (q: string) => {
    if (!liveSid || !durablePid) return;
    const n = qaTurns.length;
    setQaTurns((prev) => [...prev, { q, answer: null }]);

    if (planMode) {
      const entries: TranscriptEntry[] = [];
      noteTurn(n, { transcript: entries });
      await runOrchestration(liveSid, q, {
        onEntry: (entry) => {
          // Pushed live so the artist watches the agents work instead of a
          // spinner; a specialist refusing is the interesting part.
          entries.push(entry);
          noteTurn(n, { transcript: [...entries] });
        },
        onDecision: (r) =>
          noteTurn(n, {
            answer: r.say,
            grounded: r.grounded,
            action: r.action,
            rejectedTool: r.rejected_tool,
            followups: r.followups,
            orchestrated: r.orchestrated,
            planReason: r.plan_reason,
          }),
        onError: (message) =>
          noteTurn(n, { answer: message, grounded: false }),
      });
      return;
    }

    try {
      const r = await askAgent(liveSid, q);
      setQaTurns((prev) =>
        prev.map((t, i) =>
          i === n
            ? {
                ...t,
                answer: r.say,
                grounded: r.grounded,
                action: r.action,
                rejectedTool: r.rejected_tool,
                followups: r.followups,
              }
            : t,
        ),
      );
    } catch (err) {
      // The agent is rate-limited; /ask is not. Falling back answers the
      // question the artist actually asked instead of showing them a limit.
      if (err instanceof Error && err.message.includes("Too many")) {
        try {
          const plain = await askQuestion(liveSid, q);
          setQaTurns((prev) =>
            prev.map((t, i) =>
              i === n
                ? { ...t, answer: plain.answer, grounded: plain.grounded }
                : t,
            ),
          );
          return;
        } catch {
          // fall through to the generic message below
        }
      }
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

  const noteTurn = (turn: number, patch: Partial<(typeof qaTurns)[number]>) =>
    setQaTurns((prev) => prev.map((t, i) => (i === turn ? { ...t, ...patch } : t)));

  const dismissAction = (turn: number) =>
    noteTurn(turn, { action: null, actionNote: null });

  /**
   * Carry out one accepted proposal.
   *
   * Board navigation and the bundle export happen here in the client; a re-run
   * and a remembered preference go back to the server, which validates them
   * again — this UI is not the thing that decides they are allowed.
   */
  const acceptAction = async (turn: number) => {
    const action: AgentAction | null | undefined = qaTurns[turn]?.action;
    if (!action || actionBusy) return;
    setActionBusy(true);
    try {
      const index = typeof action.args.index === "number" ? action.args.index : null;
      switch (action.tool) {
        // All three land the artist on the same board, but they promise different
        // things, and saying "Opened pair N" for all of them made a tool that
        // showed nothing read as success. The server now refuses explain_pair and
        // show_annotated where no finding or marked image exists, so by the time
        // one arrives here the artefact is real — the note should name it.
        case "explain_pair":
        case "show_annotated":
        case "open_board":
          if (index === null) throw new Error("That pair is no longer available.");
          setBoardFocus(index);
          // show_annotated used to be byte-identical to open_board: it navigated,
          // said "Showing the marked frame for pair N", and showed an ordinary
          // in-between, because nothing in the client read `annotated_url`. The
          // note was the only thing that differed, which is how a tool that
          // displayed nothing read as success.
          if (action.tool === "show_annotated") {
            setBoardMark({ index, nonce: Date.now() });
          }
          setView("board");
          noteTurn(turn, {
            actionDone: true,
            actionNote:
              action.tool === "explain_pair"
                ? `Showing why pair ${index} was flagged.`
                : action.tool === "show_annotated"
                  ? `Showing the marked frame for pair ${index}.`
                  : `Opened pair ${index}.`,
          });
          break;
        case "export_bundle":
          if (!result) throw new Error("There is nothing to export yet.");
          await downloadBundle(result);
          noteTurn(turn, { actionDone: true, actionNote: "Bundle downloaded." });
          break;
        case "rerun_session": {
          if (!liveSid) throw new Error("This session is no longer live.");
          noteTurn(turn, { actionDone: true, actionNote: "Re-running…" });
          setRunning(true);
          setLog([]);
          setResult(null);
          setVerdicts({});
          await rerunSession(
            liveSid,
            {
              cadence:
                typeof action.args.cadence === "number" ? action.args.cadence : undefined,
              smoothness:
                typeof action.args.smoothness === "number"
                  ? action.args.smoothness
                  : undefined,
              interpolator:
                typeof action.args.interpolator === "string"
                  ? action.args.interpolator
                  : undefined,
            },
            {
              onPair: (p) => setLog((prev) => [...prev, p]),
              onResult: (r) => {
                setResult(r);
                setLiveSid(sidFromResult(r));
              },
              onError: (m) => setBanner(m),
            },
          );
          setRunning(false);
          noteTurn(turn, { actionNote: "Re-run finished." });
          break;
        }
        case "remember_memory":
          await rememberMemory(action.args);
          noteTurn(turn, { actionDone: true, actionNote: "Saved for next time." });
          break;
      }
    } catch (err) {
      // Kept on the turn rather than raised as a banner: the artist pressed a
      // button on this message, so the answer belongs next to it.
      setRunning(false);
      noteTurn(turn, {
        actionNote:
          err instanceof Error ? err.message : "That could not be carried out.",
      });
    } finally {
      setActionBusy(false);
    }
  };

  const handleSignOut = async () => {
    cacheWritesEnabled.current = false;
    activeStreamStop.current?.();
    activeStreamStop.current = null;
    clearAll();
    clearComposerInputs();
    setOwnerSub(null);
    try {
      await deleteActiveWorkspaceDatabase();
    } catch (error) {
      console.warn("could not delete active-workspace cache during sign-out", error);
    }
    await logoutCookieSession();
  };

  const resumeWorkspace = async (workspace = recoverableWorkspace) => {
    if (!workspace) return;
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      if (workspace.state === "publish_pending") {
        const published = await retryActiveWorkspacePublish(workspace.workspace_id);
        if (!published.published) throw new Error(published.error || "The session could not be published yet.");
      }
      const [cached, refreshed] = await Promise.all([
        ownerSub ? loadCache(ownerSub) : Promise.resolve(null),
        getActiveWorkspace(),
      ]);
      if (!refreshed) {
        setRecoverableWorkspace(null);
        setRunning(false);
        return;
      }
      setRecoverableWorkspace(null);
      if (refreshed.published_pid) {
        await hydratePublishedSession(refreshed.published_pid);
        if (ownerSub) await clearCache(ownerSub);
        setActiveWorkspace(null);
        setRunning(false);
        return;
      }
      // The server remains authoritative. Full active snapshot hydration and
      // replay are deliberately safe even when the browser cache is empty.
      const snapshot = refreshed.snapshot;
      const snapshotUpload = snapshot.upload?.mode
        ? {
            media: snapshot.upload.mode === "video" ? "video" as const : "keyframes" as const,
            count: snapshot.upload.filenames?.length ?? 0,
          }
        : null;
      const cacheMatches = cached?.state?.workspaceId === refreshed.workspace_id
        && cached.assets?.workspaceId === refreshed.workspace_id;
      if (cacheMatches && cached?.assets && cached.state) {
        keys.replace(cached.assets.keys);
        stagedKeys.replace(cached.assets.keys);
        setStagedVideoFile(cached.assets.video);
        setStagedMode(cached.state.mode);
        setSessionMode(cached.state.mode);
        // Local cache remains first choice. A cache written before its upload
        // turn was committed is incomplete, however, so use the manifest's
        // start-of-run descriptor immediately instead of waiting for `result`.
        setUpload(cached.state.upload ?? snapshotUpload);
        setLog(cached.state.log);
        setResult(cached.state.result);
        setVerdicts(cached.state.verdicts);
        setActiveDraftPid(cached.state.activeDraftPid);
        // Restore the conversation too. The run card used to come back on its
        // own and the chat came back empty, which reads as "the co-pilot forgot
        // everything" even though the service still had the turns.
        if (cached.state.qaTurns?.length) setQaTurns(cached.state.qaTurns);
      } else {
        if (ownerSub) await clearCache(ownerSub);
        clearAll();
        const restoredAssets = await restoreActiveInputs(refreshed);
        if (ownerSub) await saveAssets(ownerSub, restoredAssets.keys, restoredAssets.video, refreshed.workspace_id);
      }
      if (!cacheMatches || cached?.state?.revision !== refreshed.revision) {
        if (Array.isArray(snapshot.pairs)) setLog(snapshot.pairs as PairEvent[]);
        if (snapshot.result) {
          const nextResult = snapshot.result as ResultEvent;
          setResult(nextResult);
          setLiveSid(sidFromResult(nextResult));
        }
        if (snapshot.upload) {
          setStagedMode(snapshot.upload.mode === "video" ? "video" : "frames");
          setSessionMode(snapshot.upload.mode === "video" ? "video" : "frames");
          setUpload({ media: snapshot.upload.mode === "video" ? "video" : "keyframes", count: snapshot.upload.filenames?.length ?? 0 });
        }
      }
      const checkpoint = cacheMatches && cached?.state
        ? cached.state.eventSequence ?? 0
        : 0;
      setActiveWorkspace(refreshed);
      setRunning(refreshed.state === "generating");
      startActiveWorkspaceStream(refreshed, checkpoint);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : "Could not resume the workspace.");
    } finally {
      setRecoveryBusy(false);
    }
  };

  const discardWorkspace = async (workspace = recoverableWorkspace) => {
    if (!workspace) return;
    setRecoveryBusy(true);
    try {
      await discardActiveWorkspace(workspace.workspace_id);
      if (ownerSub) await clearCache(ownerSub);
      activeStreamStop.current?.();
      activeStreamStop.current = null;
      setActiveWorkspace(null);
      setRecoverableWorkspace(null);
      clearAll();
      clearComposerInputs();
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : "Could not discard the workspace.");
    } finally {
      setRecoveryBusy(false);
    }
  };

  const resumePreflightWorkspace = async () => {
    if (!preflightWorkspace) return;
    const workspace = preflightWorkspace;
    clearComposerInputs();
    setPreflightWorkspace(null);
    setPendingRun(null);
    setRecoverableWorkspace(workspace);
    await resumeWorkspace(workspace);
  };

  const discardPreflightAndRun = async () => {
    if (!preflightWorkspace || !pendingRun) return;
    const workspace = preflightWorkspace;
    const next = pendingRun;
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      await discardActiveWorkspace(workspace.workspace_id);
      if (ownerSub) await clearCache(ownerSub);
      activeStreamStop.current?.();
      activeStreamStop.current = null;
      setActiveWorkspace(null);
      setRecoverableWorkspace(null);
      setPreflightWorkspace(null);
      setPendingRun(null);
      await beginPendingRun(next);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : "Could not discard the active workspace.");
    } finally {
      setRecoveryBusy(false);
    }
  };

  const msgs: ChatMsg[] = useMemo(
    () => deriveMessages({ upload, log, result, running, banner, qa: qaTurns }),
    [upload, log, result, running, banner, qaTurns],
  );

  const openBoard = (focus: number | null) => {
    setBoardFocus(focus);
    setView("board");
  };

  const hasSession = !!upload || log.length > 0 || !!result;

  return (
    <TooltipProvider>
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
          onDeleteSession={deleteHistorySession}
          onRetryHistory={() => void loadHistory()}
          onLoadMore={() => void loadMoreHistory()}
          view={view}
          onViewChange={setView}
          previewAvailable={running || log.length > 0}
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
                  onOpenBoard={() => openBoard(null)}
                  onExport={downloadBundle}
                  onAcceptAction={(turn) => void acceptAction(turn)}
                  onDismissAction={dismissAction}
                  actionBusy={actionBusy}
                />
              ) : (
                <ChatWelcome
                  onImportFrames={importFrames}
                  onImportVideo={importVideo}
                />
              )}
              <ChatComposer
                files={stagedKeys.files}
                fileUrls={stagedKeyUrls}
                onAdd={importFrames}
                onRemove={removeComposerFrame}
                onClear={clearComposerInputs}
                mode={stagedMode}
                onModeChange={changeMode}
                interpolator={interpolator}
                setInterpolator={setInterpolator}
                cadence={cadence}
                setCadence={setCadence}
                smoothness={smoothness}
                setSmoothness={setSmoothness}
                videoFile={stagedVideoFile}
                onVideo={setComposerVideo}
                stride={stride}
                setStride={setStride}
                onRun={run}
                onRunVideo={runVideo}
                running={running}
                compact={running || log.length > 0}
                askEnabled={!!result?.artifacts && !!liveSid && !!durablePid}
                askSaving={!!result?.artifacts && !!liveSid && !durablePid}
                onAsk={onAsk}
                planMode={planMode}
                onPlanModeChange={setPlanMode}
              />
            </div>
          ) : (
            <>
              <ReviewWorkbench
                log={log}
                result={result}
                running={running}
                keyUrls={effKeyUrls}
                verdicts={verdicts}
                onVerdict={setVerdict}
                onRefill={refillKey}
                stagedRefills={stagedRefills}
                canEdit={!!liveSid && !!durablePid}
                readOnlyReason={resumeRefusal}
                onSubmitVerdicts={submitReviewVerdicts}
                onSubmitRefills={submitReviewKeys}
                onDiscardStaged={discardStagedRefills}
                onRepair={submitPairRepair}
                fps={
                  result?.sampling?.output_fps ||
                  Number(cadence) * Number(smoothness) ||
                  24
                }
                initialFocus={boardFocus}
                markPair={boardMark}
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
          <ActiveWorkspaceDialog
            workspace={preflightWorkspace ?? recoverableWorkspace}
            busy={recoveryBusy}
            error={recoveryError}
            intent={preflightWorkspace ? "run-preflight" : "recovery"}
            onResume={() => void (preflightWorkspace ? resumePreflightWorkspace() : resumeWorkspace())}
            onRetry={() => void (preflightWorkspace ? discardPreflightAndRun() : resumeWorkspace())}
            onDiscard={() => void (preflightWorkspace ? discardPreflightAndRun() : discardWorkspace())}
          />
          <Dialog open={reviewSubmit != null} onOpenChange={(open) => {
            if (!open && reviewSubmit?.error) setReviewSubmit(null);
          }}>
            <DialogContent showCloseButton={false} onEscapeKeyDown={(event) => event.preventDefault()} onPointerDownOutside={(event) => event.preventDefault()}>
              <DialogHeader className="items-center text-center">
                <DialogTitle>{reviewSubmit?.kind === "keys" ? "Applying replacement keys" : reviewSubmit?.kind === "repair" ? "Repairing the frame" : "Submitting verdicts"}</DialogTitle>
                <DialogDescription className="flex items-center justify-center gap-2 text-center">
                  {!reviewSubmit?.error && <LoaderCircle className="size-4 shrink-0 animate-spin" aria-label="Working" />}
                  <span>{reviewSubmit?.error ?? reviewSubmit?.phase}</span>
                </DialogDescription>
              </DialogHeader>
              {reviewSubmit?.error && (
                <Button type="button" onClick={() => setReviewSubmit(null)}>Return to review</Button>
              )}
            </DialogContent>
          </Dialog>
        </div>
      </SidebarProvider>
    </TooltipProvider>
  );
}
