"use client";
// Co-pilot app shell — owns all session state and switches the chat ⇄ board surfaces.
// The presentational pieces were split out into ./components/* and the logic into ./lib/*
// (this file used to be a ~1360-line monolith holding all of them).
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { PairEvent, ResultEvent, InputMode } from "./types";
import {
  runSession,
  runVideoSession,
  askAgent,
  askQuestion,
  rerunSession,
  rememberMemory,
  sendFeedback,
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
import { useActiveWorkspace } from "./lib/useActiveWorkspace";
import { deleteCacheDatabase } from "./lib/workspaceCache";
import { downloadBundle } from "./lib/exportSession";
import { ChatHeader } from "./components/chat/ChatHeader";
import { ChatView } from "./components/chat/ChatView";
import { ChatComposer } from "./components/chat/ChatComposer";
import { ChatWelcome } from "./components/chat/ChatWelcome";
import { ReviewWorkbench } from "./components/review/ReviewWorkbench";
import { ResumeWorkspaceDialog } from "./components/review/ResumeWorkspaceDialog";
import { Toast } from "./components/review/Toast";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
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

function sidFromResult(r: ResultEvent | null) {
  // The server sends the id outright. Slicing an artifact URL is the fallback for
  // sessions stored before that field existed: a republished session serves them
  // under "/sessions/{pid}/artifacts/...", which this slice cannot read, and the
  // grounded Q&A box then goes dead with no visible cause.
  if (r?.sid != null) return String(r.sid);
  const ref = r?.artifacts?.montage || r?.artifacts?.video;
  return ref?.startsWith("/session/") ? (ref.split("/")[2] ?? null) : null;
}

export default function App() {
  const router = useRouter();
  const keys = useFileSet();
  const [engines, setEngines] = useState("box");
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
  const setVerdict = (idx: number, v: "accept" | "reject") => {
    setVerdicts((prev) => {
      const n = { ...prev };
      if (n[idx] === v)
        delete n[idx]; // toggle off
      else n[idx] = v;
      return n;
    });
    // The artist's own keep/redraw call IS the per-show calibration signal the
    // QA thresholds are refit against. This control existed and never left the
    // browser. Toggling OFF sends nothing: there is no retraction endpoint, and
    // inventing one here would be guessing at what a withdrawn vote means.
    if (liveSid && verdicts[idx] !== v) {
      void sendFeedback(liveSid, idx, v === "accept" ? "up" : "down").catch(
        (err) => console.warn("could not record that verdict", err),
      );
    }
  };

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [stride, setStride] = useState("2");
  // Composer input mode, lifted here (was in ChatComposer) so BOTH the dropzone and the
  // ChatWelcome quick-import buttons share one source of truth.
  const [mode, setMode] = useState<InputMode>("frames");


  // chat-first surface state (vault 'Chat-First Copilot Surface')
  const [view, setView] = useState<"chat" | "board">("chat");
  const [boardFocus, setBoardFocus] = useState<number | null>(null);
  const [upload, setUpload] = useState<UserTurn | null>(null);
  const [qaTurns, setQaTurns] = useState<QaTurn[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  // Opt-in. The planner has never been user-facing, and deciding what to do with
  // an artist's cut is a bigger promise than answering their question — so it is
  // a choice they make per message, not a default applied to all of them.
  const [planMode, setPlanMode] = useState(false);

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
      setHistoryError(
        error instanceof Error ? error.message : "Could not load sessions.",
      );
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);
  // The unfinished-run surface. It decides WHICH state to restore and where it
  // comes from; these callbacks decide what restoring means, so the hook never
  // reaches into the run's state itself.
  const workspace = useActiveWorkspace({
    onRestoreCached: (cached, assets) => {
      keys.replace(assets.keys);
      setVideoFile(assets.video);
      setMode(cached.mode);
      setUpload(cached.upload);
      setLog(cached.log);
      setResult(cached.result);
      setLiveSid(sidFromResult(cached.result));
      setVerdicts(cached.verdicts);
      setActiveDraftPid(cached.activeDraftPid);
      setView(cached.result ? "board" : "chat");
    },
    onRestoreSnapshot: (restored, files) => {
      const snapshot = restored.snapshot;
      keys.replace(files.keys);
      setVideoFile(files.video);
      setVerdicts({});
      if (!snapshot) return;
      setMode(snapshot.upload.mode === "video" ? "video" : "frames");
      setUpload({
        media: snapshot.upload.mode === "video" ? "video" : "keyframes",
        count:
          snapshot.upload.mode === "video"
            ? 1
            : snapshot.upload.filenames.length,
      });
      setLog(snapshot.pairs);
      setResult(snapshot.result);
      setLiveSid(sidFromResult(snapshot.result));
      setView(snapshot.result ? "board" : "chat");
    },
    onEvent: (event) => {
      if (event.name === "pair") {
        const pair = event.data as unknown as PairEvent;
        if (typeof pair.index !== "number") return;
        // Replace by index rather than append: a replayed pair must not
        // double up a row the artist is already looking at.
        setLog((prev) =>
          prev.some((item) => item.index === pair.index)
            ? prev.map((item) => (item.index === pair.index ? pair : item))
            : [...prev, pair],
        );
        setRunning(true);
      } else if (event.name === "result") {
        const finished = event.data as unknown as ResultEvent;
        setResult(finished);
        setLiveSid(sidFromResult(finished));
        setRunning(false);
      } else if (event.name === "error") {
        setRunning(false);
        setBanner(
          typeof event.data.message === "string"
            ? event.data.message
            : "The recovered workspace stopped unexpectedly.",
        );
      }
    },
    onPublished: (pid) => {
      setSelectedPid(pid);
      setActiveDraftPid(null);
      void loadHistory();
    },
  });

  const { attach: workspaceAttach, adoptRunningWorkspace, saveState } = workspace;

  // Account Setup
  useEffect(() => {
    let active = true;
    getCookieSession()
      .then((session) => {
        if (!active) return;
        setAccount({
          name: session.name,
          username: session.username,
        });
        void loadHistory();
        void workspaceAttach(session.user_sub);
      })
      .catch((err) => {
        console.error("failed to load cookie session:", err);
        router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [loadHistory, router, workspaceAttach]);

  const keyUrls = useMemo(
    () => keys.files.map((f) => URL.createObjectURL(f)),
    [keys.files],
  );
  useEffect(
    () => () => keyUrls.forEach((u) => URL.revokeObjectURL(u)),
    [keyUrls],
  );

  const effKeyUrls = useMemo(() => {
    if (keyUrls.length) return keyUrls;
    const sk = result?.key_urls;
    if (!sk) return keyUrls;
    const n = Object.keys(sk).length;
    return Array.from({ length: n }, (_, i) => sk[String(i)] ?? "");
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
      setHistory((items) =>
        items.map((item) => (item.pid === selected.pid ? selected : item)),
      );
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
    setVideoFile(null);
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

  const changeMode = (next: InputMode) => {
    if (next === mode) return;
    if (next === "video")
      keys.clear(); // leaving frames → drop staged keys
    else setVideoFile(null); // leaving video → drop staged clip
    setMode(next);
  };

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
      media: "keyframes",
      count: keys.files.length,
    });
    setRunning(true);
    let claimed = false;
    try {
      await runSession(
        keys.files,
        engines,
        interpolator,
        cadence,
        smoothness,
        {
          onPair: (p) => {
            setLog((prev) => [...prev, p]);
            // The first pair means the server has opened a workspace for this
            // run. Claim it now so a reload from here can find its way back.
            if (!claimed) {
              claimed = true;
              void adoptRunningWorkspace(keys.files, null);
            }
          },
          onResult: (r) => {
            setResult(r);
            setLiveSid(sidFromResult(r));
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

  const runVideo = async () => {
    if (!videoFile) return;
    setBanner(null);
    setLog([]);
    setResult(null);
    setVerdicts({});
    setQaTurns([]);
    setLiveSid(null);
    setUpload({
      media: "video",
      count: 1,
    });
    setRunning(true);
    let claimed = false;
    try {
      await runVideoSession(
        videoFile,
        stride,
        cadence,
        smoothness,
        engines,
        interpolator,
        {
          onPair: (p) => {
            setLog((prev) => [...prev, p]);
            if (!claimed) {
              claimed = true;
              void adoptRunningWorkspace([], videoFile);
            }
          },
          onResult: (r) => {
            setResult(r);
            setLiveSid(sidFromResult(r));
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

  // The chat used to call /ask, which answers and nothing more. It now calls the
  // agent, which answers AND may propose one tool. Nothing it proposes runs
  // here: acceptAction below is the only path, and the server refuses anything
  // confirm-gated that arrives without one.
  const onAsk = async (q: string) => {
    if (!liveSid) return;
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
    clearAll();
    workspace.stopFollowing();
    // Before the cookie goes, not after: a shared studio machine must not keep
    // one artist's staged keyframes readable by whoever signs in next. A tab
    // still holding the database blocks this, and the artist is told.
    try {
      await deleteCacheDatabase();
    } catch (err) {
      console.warn("could not delete the active-workspace cache", err);
    }
    await logoutCookieSession();
  };

  // Autosave. Skipped while there is nothing worth restoring, and once the run
  // has been filed to history — at that point the history record IS the copy.
  useEffect(() => {
    if (workspace.live?.state === "published") return;
    if (!upload && log.length === 0 && !result) return;
    saveState({
      eventSequence: workspace.live?.event_sequence ?? 0,
      mode,
      upload,
      log,
      result,
      verdicts,
      activeDraftPid,
    });
  }, [
    activeDraftPid,
    log,
    mode,
    result,
    saveState,
    upload,
    verdicts,
    workspace.live,
  ]);

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
      <ResumeWorkspaceDialog
        workspace={workspace.pending}
        busy={workspace.busy}
        error={workspace.error}
        onResume={() => void workspace.resume()}
        onRetryPublish={() => void workspace.retryPublish()}
        onDiscard={() => void workspace.discard()}
      />
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
                interpolator={interpolator}
                setInterpolator={setInterpolator}
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
                fps={
                  result?.sampling?.output_fps ||
                  Number(cadence) * Number(smoothness) ||
                  24
                }
                initialFocus={boardFocus}
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
