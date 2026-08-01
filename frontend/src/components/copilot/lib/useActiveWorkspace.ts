"use client";

// Owns everything about the server-side active workspace, so CopilotApp keeps
// owning the run itself.
//
// The split that makes this work: the hook decides WHICH state to restore and
// where it comes from; the caller decides what restoring means. The hook never
// touches the run's state directly — it hands back a cached snapshot or a
// server snapshot and lets the app apply it.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  discardActiveWorkspace,
  getActiveWorkspace,
  publishActiveWorkspace,
  subscribeToWorkspace,
  type ActiveWorkspace,
  type WorkspaceEvent,
} from "@/lib/activeWorkspaceApi";
import { authenticatedFetch } from "@/lib/authenticatedApi";
import {
  cacheAssets,
  clearCache,
  purgeOtherUsers,
  readCache,
  restoreAssetsFromServer,
  type CachedAssets,
  type CachedState,
} from "./workspaceCache";

export interface RestoredFiles {
  keys: File[];
  video: File | null;
}

export interface UseActiveWorkspaceOptions {
  /** The local copy was current — restore the artist's exact screen. */
  onRestoreCached: (state: CachedState, assets: CachedAssets) => void;
  /** No usable local copy — rebuild from what the server kept. */
  onRestoreSnapshot: (
    workspace: ActiveWorkspace,
    files: RestoredFiles,
  ) => void;
  /** Live events for a run picked up mid-flight. */
  onEvent: (event: WorkspaceEvent) => void;
  /** The run reached history; `pid` is where it landed. */
  onPublished: (pid: string) => void;
}

export function useActiveWorkspace({
  onRestoreCached,
  onRestoreSnapshot,
  onEvent,
  onPublished,
}: UseActiveWorkspaceOptions) {
  const [userSub, setUserSub] = useState<string | null>(null);
  const [pending, setPending] = useState<ActiveWorkspace | null>(null);
  const [live, setLive] = useState<ActiveWorkspace | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Whether the local cache is safe to write. It is not, if purging another
  // account's data failed on sign-in: writing then risks mixing two artists'
  // work on one machine, and losing a resume is the lesser harm.
  const cacheUsable = useRef(false);
  const cursor = useRef(0);
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => () => unsubscribe.current?.(), []);

  const follow = useCallback(
    (workspace: ActiveWorkspace, from: number) => {
      unsubscribe.current?.();
      cursor.current = from;
      unsubscribe.current = subscribeToWorkspace(
        workspace.workspace_id,
        from,
        {
          onEvent: (event) => {
            cursor.current = event.sequence;
            if (event.name === "publish") {
              if (event.data.published === true) {
                const pid =
                  typeof event.data.pid === "string" ? event.data.pid : null;
                if (pid) {
                  onPublished(pid);
                  if (userSub) void clearCache(userSub).catch(() => undefined);
                  setLive(null);
                  setPending(null);
                  return;
                }
                setError(
                  "The session was saved but the server did not say where.",
                );
                return;
              }
              // Saving refused: keep it, and say so rather than dropping it.
              setLive({ ...workspace, state: "publish_pending" });
              setPending({ ...workspace, state: "publish_pending" });
              setError(
                typeof event.data.error === "string"
                  ? event.data.error
                  : "The session is ready, but saving it needs a retry.",
              );
              return;
            }
            onEvent(event);
          },
        },
      );
      setLive(workspace);
    },
    [onEvent, onPublished, userSub],
  );

  /** Sign-in: adopt the account, clear other accounts, then look for a run. */
  const attach = useCallback(async (sub: string) => {
    setUserSub(sub);
    try {
      await purgeOtherUsers(sub);
      cacheUsable.current = true;
    } catch (err) {
      cacheUsable.current = false;
      console.warn("could not purge another account's workspace cache", err);
    }
    try {
      const workspace = await getActiveWorkspace();
      if (!workspace) return;
      if (workspace.published_pid) {
        // Already filed; nothing to offer, just stop holding a stale copy.
        await clearCache(sub).catch(() => undefined);
        return;
      }
      setPending(workspace);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not check for an unfinished run.",
      );
    }
  }, []);

  /**
   * A run has started producing pairs — the server has opened a workspace for
   * it. Claim it so a reload mid-run can find its way back.
   */
  const adoptRunningWorkspace = useCallback(
    async (keys: File[], video: File | null) => {
      try {
        const workspace = await getActiveWorkspace();
        if (!workspace) return;
        cursor.current = workspace.event_sequence;
        setLive(workspace);
        if (cacheUsable.current && userSub) {
          await cacheAssets(userSub, keys, video, workspace.workspace_id).catch(
            () => undefined,
          );
        }
      } catch {
        // A run that cannot be made resumable is still a run; never break it.
      }
    },
    [userSub],
  );

  const resume = useCallback(async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const cached = userSub ? await readCache(userSub) : null;
      const matches =
        cached?.state?.workspaceId === pending.workspace_id &&
        cached?.assets?.workspaceId === pending.workspace_id &&
        cached?.state?.revision === pending.revision;

      if (matches && cached?.state && cached.assets) {
        onRestoreCached(cached.state, cached.assets);
      } else {
        // No usable local copy — another device, a cleared profile, or the
        // server moved on. Rebuild from what the server kept.
        const files = await restoreAssetsFromServer(
          pending.assets,
          pending.artifact_urls,
          pending.snapshot?.upload.filenames ?? [],
          (url) => authenticatedFetch(url, { cache: "no-store" }),
        );
        onRestoreSnapshot(pending, files);
      }
      setPending(null);
      if (pending.state === "draft") follow(pending, pending.event_sequence);
      else setLive(pending);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not resume the workspace.",
      );
    } finally {
      setBusy(false);
    }
  }, [follow, onRestoreCached, onRestoreSnapshot, pending, userSub]);

  const retryPublish = useCallback(async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await publishActiveWorkspace(pending.workspace_id);
      if (!outcome.published || !outcome.pid) {
        throw new Error(outcome.error ?? "The session could not be saved yet.");
      }
      onPublished(outcome.pid);
      if (userSub) await clearCache(userSub).catch(() => undefined);
      setPending(null);
      setLive(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save the session.",
      );
    } finally {
      setBusy(false);
    }
  }, [onPublished, pending, userSub]);

  const discard = useCallback(async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await discardActiveWorkspace(pending.workspace_id);
      if (userSub) await clearCache(userSub).catch(() => undefined);
      unsubscribe.current?.();
      unsubscribe.current = null;
      setPending(null);
      setLive(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not discard the workspace.",
      );
    } finally {
      setBusy(false);
    }
  }, [pending, userSub]);

  /** Persist the artist's screen so a reload restores it exactly. */
  const saveState = useCallback(
    (state: Omit<CachedState, "expiresAt" | "workspaceId" | "revision">) => {
      if (!cacheUsable.current || !userSub) return;
      void import("./workspaceCache").then(({ cacheState }) =>
        cacheState(userSub, {
          ...state,
          workspaceId: live?.workspace_id ?? null,
          revision: live?.revision ?? null,
        }).catch((err) =>
          console.warn("could not cache active workspace state", err),
        ),
      );
    },
    [live, userSub],
  );

  return {
    pending,
    live,
    busy,
    error,
    attach,
    adoptRunningWorkspace,
    resume,
    retryPublish,
    discard,
    saveState,
    stopFollowing: () => {
      unsubscribe.current?.();
      unsubscribe.current = null;
    },
  };
}
