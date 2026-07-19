"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { BrandIcon } from "../../../common/BrandIcon";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { InputMode } from "../../types";
import { isPng, isVideoFile } from "../../lib/media";
import { ChevronDown, ChevronRight, X } from "lucide-react";

interface KeyframeDropzoneProps {
  files: File[];
  urls: string[];
  onAdd: (files: File[]) => void;
  onRemove: (f: File) => void;
  onClear: () => void;
  compact?: boolean;
  mode: InputMode; // "frames" (PNG keys) | "video" (single clip)
  onModeChange: (m: InputMode) => void;
  videoFile: File | null;
  onVideo: (f: File | null) => void;
}
/* eslint-disable @next/next/no-img-element */
// keyframe / video dropzone: the peg-bar light-table (drag-drop + cel contact-sheet),
// now also the single intake + preview surface for a whole-video clip (mode selector in the header)
export function KeyframeDropzone({
  files,
  urls,
  onAdd,
  onRemove,
  onClear,
  compact,
  mode,
  onModeChange,
  videoFile,
  onVideo,
}: KeyframeDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(true); // expand / collapse the preview
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fold the preview once a run exists
    if (compact) setOpen(false);
  }, [compact]); // once a run exists, fold the preview to reclaim top space

  // still-frame thumbnail source for the video mode — created here, revoked on change/unmount
  const videoUrl = useMemo(
    () => (videoFile ? URL.createObjectURL(videoFile) : null),
    [videoFile],
  );
  useEffect(
    () => () => {
      if (videoUrl) URL.revokeObjectURL(videoUrl);
    },
    [videoUrl],
  );

  // filter for real on BOTH intake paths (the `isPng`/`isVideoFile` predicates are shared with
  // ChatWelcome's import buttons — see lib/media). frames: keep only PNG cels.
  const acceptPng = (list: FileList | null) =>
    onAdd(Array.from(list ?? []).filter(isPng));
  // video: take the first video file from the set
  const acceptVideo = (list: FileList | null) => {
    const f = Array.from(list ?? []).find(isVideoFile);
    if (f) onVideo(f);
  };
  const isVideo = mode === "video";
  const handleModeChange = (value: string) => {
    if (value === "frames" || value === "video") onModeChange(value);
  };

  return (
    <div className="dropzone-wrap">
      <div className="flex flex-col gap-2">
        {/* MODE SELECTOR — sits outside the clickable box so it never opens the file dialog */}
        <Field orientation="horizontal" className="inline-flex w-auto items-center gap-1.5 self-start font-mono text-[11px] tracking-[0.08em] text-ash uppercase">
          <FieldLabel className="font-mono text-[11px] tracking-[0.08em] text-ash uppercase">input</FieldLabel>
          <Select value={mode} onValueChange={handleModeChange}>
            <SelectTrigger size="sm" className="w-auto font-mono text-[13px] text-washi">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="frames">Frames (PNG)</SelectItem>
              <SelectItem value="video">Video (MP4)</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        {/* DROP BOX */}
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
            if (isVideo) acceptVideo(e.dataTransfer.files);
            else acceptPng(e.dataTransfer.files);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept={isVideo ? "video/mp4,video/*" : "image/png"}
            multiple={!isVideo}
            className="sr-only"
            onChange={(e) => {
              // snapshot before resetting value (the load→clear→load bug; see FilePicker)
              if (isVideo) {
                const f = e.currentTarget.files?.[0] ?? null;
                e.currentTarget.value = "";
                if (f && isVideoFile(f)) onVideo(f);
              } else {
                const picked = Array.from(e.currentTarget.files ?? []).filter(
                  isPng,
                );
                e.currentTarget.value = "";
                onAdd(picked);
              }
            }}
          />
          <BrandIcon />
          <span className="dropzone-cap">
            {isVideo
              ? videoFile
                ? "clip loaded · click to replace"
                : "Drop a video — or click to load"
              : files.length === 0
                ? "Drop PNG keyframes — or click to load"
                : `${files.length} keyframes · drop or click to add more`}
          </span>
          <span className="dropzone-sub">
            {isVideo ? "MP4 · one clip" : "PNG · 2+ keys to run"}
          </span>
        </div>
      </div>

      {/* PREVIEW — frames contact-sheet */}
      {!isVideo && files.length > 0 && (
        <>
          <div className="celstrip-head">
            <button
              type="button"
              className="celstrip-toggle"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <span className="celstrip-caret" aria-hidden="true">
                {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              </span>{" "}
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
                      title={`Remove ${f.name}`}
                      aria-label={`Remove ${f.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(f);
                      }}
                    >
                      <X className="size-3" aria-hidden="true" />
                    </button>
                  </div>
                  <figcaption>{f.name}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </>
      )}

      {/* PREVIEW — single video clip (still first-frame thumbnail, no transport) */}
      {isVideo && videoFile && videoUrl && (
        <>
          <div className="celstrip-head">
            <button
              type="button"
              className="celstrip-toggle"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <span className="celstrip-caret" aria-hidden="true">
                {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              </span> video clip
            </button>
            <button
              type="button"
              className="cel-clear"
              onClick={() => onVideo(null)}
            >
              Clear
            </button>
          </div>
          {open && (
            <div className="celstrip">
              <figure className="cel">
                <div className="cel-frame">
                  {/* #t=0.1 forces a first-frame paint; no `controls` = thumbnail only */}
                  <video
                    src={`${videoUrl}#t=0.1`}
                    preload="metadata"
                    muted
                    playsInline
                  />
                  <button
                    type="button"
                    className="cel-x"
                    title={`Remove ${videoFile.name}`}
                    aria-label={`Remove ${videoFile.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onVideo(null);
                    }}
                  >
                    <X className="size-3" aria-hidden="true" />
                  </button>
                </div>
                <figcaption>{videoFile.name}</figcaption>
              </figure>
            </div>
          )}
        </>
      )}
    </div>
  );
}
