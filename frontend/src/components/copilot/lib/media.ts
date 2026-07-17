// media intake predicates — shared by the KeyframeDropzone (drag/drop + click) and the
// ChatWelcome quick-import buttons so every surface agrees on what counts as a keyframe cel
// vs a clip. `accept="…"` on a file input is only a dialog HINT (bypassable via "All files",
// and never enforced on drag-drop), so callers must filter for real on every intake path.
export const isPng = (f: File) =>
  f.type === "image/png" || f.name.toLowerCase().endsWith(".png");

const VIDEO_EXTENSIONS = /\.(mp4|webm|mov|m4v|avi|mkv)$/i;

export const isVideoFile = (f: File) =>
  f.type.startsWith("video/") || VIDEO_EXTENSIONS.test(f.name);
