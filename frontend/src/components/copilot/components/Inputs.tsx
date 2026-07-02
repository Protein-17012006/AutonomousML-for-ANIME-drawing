// Shared input primitives — moved out of App.tsx so the chat composer and the
// legacy panels import ONE definition (starts the audit-#7 split).
import { useEffect, useRef, useState } from "react";

export function FilePicker({ id, label, onAdd }: { id: string; label: string; onAdd: (files: File[]) => void }) {
  return (
    <>
      <input
        type="file"
        id={id}
        accept="image/png"
        multiple
        className="visually-hidden"
        onChange={(e) => {
          // Snapshot the files NOW: in Chromium, resetting input.value="" empties the
          // live FileList, so handing it to a deferred setState updater loses everything
          // (the load→clear→load bug). A plain array is independent of the input.
          const picked = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = ""; // allow re-picking the same files (re-fires change)
          onAdd(picked);
        }}
      />
      <label htmlFor={id} className="btn btn-ghost">{label}</label>
    </>
  );
}

/* ---------- peg-bar brand glyph (the strip every animation sheet clamps onto) ---------- */
export function PegBar() {
  return (
    <svg className="pegbar" viewBox="0 0 44 18" aria-hidden="true">
      <rect className="pb-bar" x="0" y="3" width="44" height="12" rx="3" />
      <rect className="pb-hole" x="6" y="6" width="7" height="6" rx="3" />
      <circle className="pb-hole" cx="22" cy="9" r="3.4" />
      <rect className="pb-hole" x="31" y="6" width="7" height="6" rx="3" />
      <circle className="pb-ring" cx="22" cy="9" r="3.4" />
    </svg>
  );
}

/* ---------- keyframe dropzone: the peg-bar light-table (drag-drop + cel contact-sheet) ---------- */
export function KeyframeDropzone({ files, urls, onAdd, onRemove, onClear, compact }: {
  files: File[]; urls: string[]; onAdd: (files: File[]) => void; onRemove: (f: File) => void; onClear: () => void; compact?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(true);   // expand / collapse the cel contact-sheet
  useEffect(() => { if (compact) setOpen(false); }, [compact]); // once a run exists, fold the contact-sheet to reclaim top space
  // drop accepts only PNG cels (the click path already filters via accept="image/png")
  const acceptPng = (list: FileList | null) =>
    onAdd(Array.from(list ?? []).filter((f) => f.type === "image/png" || f.name.toLowerCase().endsWith(".png")));
  return (
    <div className="dropzone-wrap">
      <div
        className={`dropzone${over ? " is-over" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); acceptPng(e.dataTransfer.files); }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/png"
          multiple
          className="visually-hidden"
          onChange={(e) => {
            // snapshot before resetting value (the load→clear→load bug; see FilePicker)
            const picked = Array.from(e.currentTarget.files ?? []);
            e.currentTarget.value = "";
            onAdd(picked);
          }}
        />
        <PegBar />
        <span className="dropzone-cap">
          {files.length === 0 ? "Drop PNG keyframes — or click to load" : `${files.length} keyframes · drop or click to add more`}
        </span>
        <span className="dropzone-sub">PNG · 2+ keys to run</span>
      </div>
      {files.length > 0 && (
        <>
          <div className="celstrip-head">
            <button type="button" className="celstrip-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              <span className="celstrip-caret">{open ? "▾" : "▸"}</span> {files.length} keyframes
            </button>
            <button type="button" className="cel-clear" onClick={onClear}>Clear all</button>
          </div>
          {open && (
            <div className="celstrip">
              {files.map((f, i) => (
                <figure className="cel" key={f.name + f.size}>
                  <div className="cel-frame">
                    <img src={urls[i]} alt={f.name} draggable={false} />
                    <span className="cel-pegs" aria-hidden="true" />
                    <button type="button" className="cel-x" title={`remove ${f.name}`}
                      onClick={(e) => { e.stopPropagation(); onRemove(f); }}>×</button>
                  </div>
                  <figcaption>{f.name}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Truncate a long video filename for the compact run button — keeping the full name in
 *  the button's `title`. A long name (e.g. original_frieren_h264.mp4) otherwise inflates the
 *  auto-sized controls column and starves the 1fr thesis column → the header squishes. */
export function shortName(name: string, head = 14): string {
  if (name.length <= head + 8) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  return name.slice(0, head) + "…" + ext;
}
