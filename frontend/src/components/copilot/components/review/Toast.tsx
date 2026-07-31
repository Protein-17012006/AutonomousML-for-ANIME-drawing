// Toast: a correction-stamp slide-in for run errors, closed explicitly by the artist.
// Extracted from CopilotApp.tsx.
import { Button } from "@/components/ui/button";
import { TriangleAlert, X } from "lucide-react";

export function Toast({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  return (
    <div className="toast" role="alert">
      <span className="toast-mark" aria-hidden="true">
        <TriangleAlert className="size-3.5" />
      </span>
      <span className="toast-msg">{message}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="shrink-0 text-washi/60 hover:bg-transparent hover:text-white"
        onClick={onClose}
        aria-label="Dismiss notification"
      >
        <X className="size-3.5" aria-hidden="true" />
      </Button>
    </div>
  );
}
