"use client";

import { useState, useRef, useEffect } from "react";
import { BrandIcon } from "../../../common/BrandIcon";

interface KeyframeDropzoneProps {
  files: File[];
  urls: string[];
  onAdd: (files: File[]) => void;
  onRemove: (f: File) => void;
  onClear: () => void;
  compact?: boolean;
}
/* eslint-disable @next/next/no-img-element */
// keyframe dropzone: the peg-bar light-table (drag-drop + cel contact-sheet)
export function KeyframeDropzone({
  files,
  urls,
  onAdd,
  onRemove,
  onClear,
  compact,
}: KeyframeDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(true); // expand / collapse the cel contact-sheet
  useEffect(() => {
    if (compact) setOpen(false);
  }, [compact]); // once a run exists, fold the contact-sheet to reclaim top space
  // drop accepts only PNG cels (the click path already filters via accept="image/png")
  const acceptPng = (list: FileList | null) =>
    onAdd(
      Array.from(list ?? []).filter(
        (f) => f.type === "image/png" || f.name.toLowerCase().endsWith(".png"),
      ),
    );
  return (
    <div className="dropzone-wrap">
      <div
        className={`dropzone${over ? " is-over" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          acceptPng(e.dataTransfer.files);
        }}
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
        <BrandIcon />
        <span className="dropzone-cap">
          {files.length === 0
            ? "Drop PNG keyframes — or click to load"
            : `${files.length} keyframes · drop or click to add more`}
        </span>
        <span className="dropzone-sub">PNG · 2+ keys to run</span>
      </div>
      {files.length > 0 && (
        <>
          <div className="celstrip-head">
            <button
              type="button"
              className="celstrip-toggle"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <span className="celstrip-caret">{open ? "▾" : "▸"}</span>{" "}
              {files.length} keyframes
            </button>
            <button type="button" className="cel-clear" onClick={onClear}>
              Clear all
            </button>
          </div>
          {open && (
            <div className="celstrip">
              {files.map((f, i) => (
                <figure className="cel" key={f.name + f.size}>
                  <div className="cel-frame">
                    <img src={urls[i]} alt={f.name} draggable={false} />
                    <span className="cel-pegs" aria-hidden="true" />
                    <button
                      type="button"
                      className="cel-x"
                      title={`remove ${f.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(f);
                      }}
                    >
                      ×
                    </button>
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
