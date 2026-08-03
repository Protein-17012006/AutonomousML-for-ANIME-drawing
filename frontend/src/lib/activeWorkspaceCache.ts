"use client";

import type { PairEvent, ResultEvent } from "@/components/copilot/types";
import type { QaTurn } from "@/components/copilot/lib/chatModel";

const DB_NAME = "copilot-active-workspace";
const ASSETS = "assets";
const STATE = "state";
const TTL = 24 * 60 * 60 * 1000;

// IndexedDB transactions from separate React effects otherwise race each other:
// an older asynchronous save can commit after a publish receipt has deleted the
// cache. Keep this small, in-tab write queue so successful promotion is a final
// cache operation for that owner.
let writeTail: Promise<void> = Promise.resolve();

function enqueueWrite<T>(operation: () => Promise<T>): Promise<T> {
  const result = writeTail.then(operation, operation);
  writeTail = result.then(() => undefined, () => undefined);
  return result;
}

export interface CachedState {
  expiresAt: number;
  revision: number | null;
  workspaceId?: string | null;
  eventSequence?: number;
  mode: "frames" | "video";
  upload: { media: "keyframes" | "video"; count: number } | null;
  log: PairEvent[];
  result: ResultEvent | null;
  verdicts: Record<number, "accept" | "reject">;
  activeDraftPid: string | null;
  /** The conversation itself.
   *
   * Only `/ask` turns are written to the durable transcript; an agent or
   * orchestrated turn lives in the service's in-process session state, which the
   * UI has no route to read back. So without this the run card returned from
   * cache after a remount and the chat came back EMPTY — the artist's questions,
   * the agent's answers and the whole planner/triage/perception transcript gone
   * from the screen while the server still remembered them.
   */
  qaTurns?: QaTurn[];
}

export interface CachedAssets { expiresAt: number; workspaceId: string | null; keys: File[]; video: File | null }

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(ASSETS)) request.result.createObjectStore(ASSETS);
      if (!request.result.objectStoreNames.contains(STATE)) request.result.createObjectStore(STATE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function get<T>(store: string, key: string): Promise<T | null> {
  const database = await db();
  try {
    return await new Promise<T | null>((resolve, reject) => {
      const request = database.transaction(store).objectStore(store).get(key);
      request.onsuccess = () => resolve((request.result as T | undefined) ?? null);
      request.onerror = () => reject(request.error);
    });
  } finally { database.close(); }
}

async function putNow(store: string, key: string, value: unknown) {
  const database = await db();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(store, "readwrite");
      transaction.objectStore(store).put(value, key);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  } finally { database.close(); }
}

export const saveAssets = (owner: string, keys: File[], video: File | null, workspaceId: string | null = null) =>
  enqueueWrite(() => putNow(ASSETS, owner, { expiresAt: Date.now() + TTL, workspaceId, keys, video } satisfies CachedAssets));

export const saveState = (owner: string, state: Omit<CachedState, "expiresAt">) =>
  enqueueWrite(() => putNow(STATE, owner, { ...state, expiresAt: Date.now() + TTL } satisfies CachedState));

export async function loadCache(owner: string) {
  const [assets, state] = await Promise.all([get<CachedAssets>(ASSETS, owner), get<CachedState>(STATE, owner)]);
  const now = Date.now();
  return { assets: assets?.expiresAt && assets.expiresAt > now ? assets : null, state: state?.expiresAt && state.expiresAt > now ? state : null };
}

export async function clearCache(owner: string) {
  return enqueueWrite(async () => {
    const database = await db();
    try {
      await Promise.all([ASSETS, STATE].map((store) => new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(store, "readwrite");
        transaction.objectStore(store).delete(owner);
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      })));
    } finally { database.close(); }
  });
}

/**
 * Explicit sign-out is a privacy boundary, not a recoverable-session boundary.
 * Delete the database itself so a shared browser retains neither account keys nor
 * empty object-store schema after the user has signed out.
 */
export function deleteActiveWorkspaceDatabase() {
  return enqueueWrite(() => new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Active-workspace cache is still open in another tab."));
  }));
}

/** Remove cached artist media from every other account on this browser/origin.
 * Run only after `/auth/me` has identified the current cookie owner. */
export async function purgeForeignCaches(currentOwner: string) {
  return enqueueWrite(async () => {
    const database = await db();
    try {
      for (const store of [ASSETS, STATE]) {
        await new Promise<void>((resolve, reject) => {
          const transaction = database.transaction(store, "readwrite");
          const objectStore = transaction.objectStore(store);
          const cursor = objectStore.openCursor();
          cursor.onsuccess = () => {
            const current = cursor.result;
            if (!current) return;
            if (current.key !== currentOwner) current.delete();
            current.continue();
          };
          transaction.oncomplete = () => resolve();
          transaction.onerror = () => reject(transaction.error);
        });
      }
    } finally { database.close(); }
  });
}
