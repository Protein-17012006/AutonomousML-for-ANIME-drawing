// file accumulation (dedup by name+size, sorted) — extracted from CopilotApp.tsx.
import { useCallback, useMemo, useState } from "react";

const sameFile = (a: File, b: File) =>
  a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

export function useFileSet() {
  const [files, setFiles] = useState<File[]>([]);
  // `incoming` MUST be a plain array snapshotted at the event (see FilePicker): a live
  // FileList is emptied by the input.value="" reset before this deferred updater runs.
  const add = useCallback((incoming: File[]) => {
    if (incoming.length === 0) return;
    setFiles((prev) => {
      const next = [...prev];
      for (const f of incoming) {
        if (!next.some((s) => sameFile(s, f))) next.push(f);
      }
      next.sort((a, b) => a.name.localeCompare(b.name));
      return next;
    });
  }, []);
  // positional insert (NO re-sort) — the authoritative spot for a drawn breakdown key,
  // kept in lockstep with the server's positional insert at the same index (draw-key loop).
  const insertAt = useCallback((pos: number, file: File) => {
    setFiles((prev) => {
      if (prev.some((existing) => sameFile(existing, file))) return prev;
      const next = [...prev];
      next.splice(Math.max(0, Math.min(pos, next.length)), 0, file);
      return next;
    });
  }, []);
  // cull a wrong genga before Run (dedup key = name+size, matching `add`)
  const remove = useCallback((file: File) =>
    setFiles((prev) => prev.filter((existing) => !sameFile(existing, file))), []);
  const clear = useCallback(() => setFiles([]), []);
  const replace = useCallback((next: File[]) => setFiles(next), []);
  return useMemo(() => ({ files, add, insertAt, remove, clear, replace }),
    [files, add, insertAt, remove, clear, replace]);
}
