"use client";

// Local half of the active workspace.
//
// The server keeps the run — its events, its snapshot, its uploads. This keeps
// the things the server should never hold: the artist's actual File objects and
// the state of their screen. A resume reads from here first and falls back to
// the server's snapshot, which is what makes resuming on the SAME machine
// instant and resuming on another one possible at all.
//
// Everything is keyed by the Cognito `sub`. Two accounts on one browser must
// never see each other's work, so signing in purges every other key.

import type { PairEvent, ResultEvent, InputMode } from "../types";
import type { UserTurn } from "./chatModel";

const DB_NAME = "copilot-active-workspace";
const DB_VERSION = 1;
const ASSETS = "assets";
const STATE = "state";

/** Uploads and view state are working copies, not a record. A day is long
 *  enough to come back to yesterday's run and short enough not to hoard files. */
const TTL_MS = 24 * 60 * 60 * 1000;

export interface CachedAssets {
  expiresAt: number;
  workspaceId: string | null;
  keys: File[];
  video: File | null;
}

export interface CachedState {
  expiresAt: number;
  workspaceId: string | null;
  /** Compared against the server's `revision`; a mismatch means this copy is
   *  stale and the snapshot wins. */
  revision: number | null;
  eventSequence: number;
  mode: InputMode;
  upload: UserTurn | null;
  log: PairEvent[];
  result: ResultEvent | null;
  verdicts: Record<number, "accept" | "reject">;
  activeDraftPid: string | null;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(ASSETS)) db.createObjectStore(ASSETS);
      if (!db.objectStoreNames.contains(STATE)) db.createObjectStore(STATE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function read<T>(store: string, key: string): Promise<T | null> {
  const db = await openDb();
  try {
    return await new Promise<T | null>((resolve, reject) => {
      const request = db.transaction(store).objectStore(store).get(key);
      request.onsuccess = () => resolve((request.result as T) ?? null);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

async function write(store: string, key: string, value: unknown): Promise<void> {
  const db = await openDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, "readwrite");
      tx.objectStore(store).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export function cacheAssets(
  userSub: string,
  keys: File[],
  video: File | null,
  workspaceId: string | null = null,
): Promise<void> {
  return write(ASSETS, userSub, {
    expiresAt: Date.now() + TTL_MS,
    workspaceId,
    keys,
    video,
  } satisfies CachedAssets);
}

export function cacheState(
  userSub: string,
  state: Omit<CachedState, "expiresAt">,
): Promise<void> {
  return write(STATE, userSub, {
    ...state,
    expiresAt: Date.now() + TTL_MS,
  } satisfies CachedState);
}

/** Both halves for one user, with anything past its TTL reported as absent. */
export async function readCache(userSub: string): Promise<{
  assets: CachedAssets | null;
  state: CachedState | null;
}> {
  const [assets, state] = await Promise.all([
    read<CachedAssets>(ASSETS, userSub),
    read<CachedState>(STATE, userSub),
  ]);
  const now = Date.now();
  return {
    assets: assets && assets.expiresAt > now ? assets : null,
    state: state && state.expiresAt > now ? state : null,
  };
}

export async function clearCache(userSub: string): Promise<void> {
  const db = await openDb();
  try {
    await Promise.all(
      [ASSETS, STATE].map(
        (store) =>
          new Promise<void>((resolve, reject) => {
            const tx = db.transaction(store, "readwrite");
            tx.objectStore(store).delete(userSub);
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
          }),
      ),
    );
  } finally {
    db.close();
  }
}

/**
 * Drop every user's cache except this one.
 *
 * Called on sign-in. A shared browser is the ordinary case for a studio
 * machine, and one artist's staged keyframes must not survive into another
 * artist's session.
 */
export async function purgeOtherUsers(userSub: string): Promise<void> {
  const db = await openDb();
  try {
    await Promise.all(
      [ASSETS, STATE].map(
        (store) =>
          new Promise<void>((resolve, reject) => {
            const tx = db.transaction(store, "readwrite");
            const objectStore = tx.objectStore(store);
            const request = objectStore.getAllKeys();
            request.onsuccess = () => {
              for (const key of request.result) {
                if (key !== userSub) objectStore.delete(key);
              }
            };
            request.onerror = () => reject(request.error);
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
          }),
      ),
    );
  } finally {
    db.close();
  }
}

/**
 * Delete the whole database, for sign-out.
 *
 * Fails loudly when another tab still holds it open: silently leaving one
 * artist's files on a shared machine is the worse outcome.
 */
export function deleteCacheDatabase(): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    request.onblocked = () =>
      reject(new Error("Active-workspace cache is still open in another tab."));
  });
}

/**
 * Rebuild the artist's uploaded files from the server's copies.
 *
 * The path for resuming somewhere the local cache is empty — another machine,
 * another browser, a cleared profile. Every asset must have a URL; one without
 * is a server-side bug and is reported rather than skipped, because a run
 * silently missing half its keys looks like the artist's mistake.
 */
export async function restoreAssetsFromServer(
  assets: { kind: "input-key" | "input-video"; name: string }[],
  artifactUrls: Record<string, string>,
  filenames: string[],
  fetcher: (url: string) => Promise<Response>,
): Promise<{ keys: File[]; video: File | null }> {
  const fetchOne = async (name: string): Promise<Blob> => {
    const url = artifactUrls[name];
    if (!url) {
      throw new Error("The active workspace is missing a protected input URL.");
    }
    const response = await fetcher(url);
    if (!response.ok) {
      throw new Error(`Could not restore an uploaded asset (${response.status}).`);
    }
    return response.blob();
  };

  const video = assets.find((asset) => asset.kind === "input-video");
  if (video) {
    const blob = await fetchOne(video.name);
    return {
      keys: [],
      video: new File([blob], filenames[0] ?? video.name, {
        type: blob.type || "video/mp4",
      }),
    };
  }

  const inputKeys = assets
    .filter((asset) => asset.kind === "input-key")
    .sort((a, b) => a.name.localeCompare(b.name));
  const keys = await Promise.all(
    inputKeys.map(async (asset, index) => {
      const blob = await fetchOne(asset.name);
      return new File([blob], filenames[index] ?? asset.name, {
        type: blob.type || "image/png",
      });
    }),
  );
  return { keys, video: null };
}
