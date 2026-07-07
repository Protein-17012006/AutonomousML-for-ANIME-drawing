// toast: a correction-stamp slide-in for run errors (akaire body, draining ao timer).
// Extracted from CopilotApp.tsx.
import { useEffect, useRef } from "react";

export function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  const closeRef = useRef(onClose);
  // keep the ref pointing at the latest onClose without resetting the dismiss timer
  useEffect(() => { closeRef.current = onClose; });
  // auto-dismiss; the timer resets only on a NEW message (App keys the toast by message)
  useEffect(() => {
    const id = window.setTimeout(() => closeRef.current(), 5200);
    return () => window.clearTimeout(id);
  }, [message]);
  return (
    <div className="toast" role="alert">
      <span className="toast-mark" aria-hidden="true" />
      <span className="toast-msg">{message}</span>
      <button type="button" className="toast-x" onClick={onClose} aria-label="dismiss">×</button>
      <span className="toast-timer" aria-hidden="true" />
    </div>
  );
}
